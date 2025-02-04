from __future__ import annotations
import gc
import os
import traceback
import typing as t

import torch

import bentoml
import openllm
from openllm_core._schemas import CompletionChunk, GenerationOutput
from openllm_core.exceptions import OpenLLMException
from openllm_core.utils import first_not_none, is_vllm_available

__all__ = ['runnable']


def runnable(backend=None):
  backend = first_not_none(backend, os.getenv('OPENLLM_BACKEND'), default='vllm' if is_vllm_available() else 'pt')
  return vLLMRunnable if backend == 'vllm' else PyTorchRunnable


class vLLMRunnable(bentoml.Runnable):
  SUPPORTED_RESOURCES = ('nvidia.com/gpu', 'amd.com/gpu', 'cpu')
  SUPPORTS_CPU_MULTI_THREADING = True

  def __init__(self, llm):
    try:
      import vllm
    except ImportError:
      raise OpenLLMException('vLLM is not installed. Please install it via `pip install "openllm[vllm]"`.') from None
    self.config = llm.config
    num_gpus, dev = 1, openllm.utils.device_count()
    if dev >= 2:
      num_gpus = min(dev // 2 * 2, dev)
    quantization = None
    if llm.quantise and llm.quantise in {'awq', 'squeezellm'}:
      quantization = llm.quantise
    try:
      self.model = vllm.AsyncLLMEngine.from_engine_args(
        vllm.AsyncEngineArgs(
          model=llm.bentomodel.path,
          tokenizer=llm.bentomodel.path,
          trust_remote_code=llm.trust_remote_code,
          tokenizer_mode='auto',
          tensor_parallel_size=num_gpus,
          dtype=str(llm._torch_dtype).split('.')[-1],
          quantization=quantization,
          worker_use_ray=False,
          engine_use_ray=False,
        )
      )
    except Exception as err:
      traceback.print_exc()
      raise OpenLLMException(f'Failed to initialise vLLMEngine due to the following error:\n{err}') from err

  @bentoml.Runnable.method(batchable=False)
  async def generate_iterator(self, prompt_token_ids, request_id, stop=None, adapter_name=None, **attrs):
    if adapter_name is not None:
      raise NotImplementedError('Adapter is not supported with vLLM.')
    stop_: set[str] = set()
    if isinstance(stop, str) and stop != '':
      stop_.add(stop)
    elif isinstance(stop, t.Iterable):
      stop_.update(stop)

    temperature = attrs.pop('temperature', self.config['temperature'])
    top_p = attrs.pop('top_p', self.config['top_p'])
    if temperature <= 1e-5:
      top_p = 1.0
    sampling_params = self.config.model_construct_env(
      stop=list(stop_), temperature=temperature, top_p=top_p, **attrs
    ).to_sampling_config()

    async for request_output in self.model.generate(None, sampling_params, request_id, prompt_token_ids):
      # XXX: Need to write a hook for serialisation None correctly
      if request_output.prompt_logprobs is not None:
        request_output.prompt_logprobs = [it if it else {} for it in request_output.prompt_logprobs]
      yield GenerationOutput.from_vllm(request_output).model_dump_json()


class PyTorchRunnable(bentoml.Runnable):
  SUPPORTED_RESOURCES = ('nvidia.com/gpu', 'amd.com/gpu', 'cpu')
  SUPPORTS_CPU_MULTI_THREADING = True

  def __init__(self, llm):
    self.model = llm.model
    self.tokenizer = llm.tokenizer
    self.config = llm.config

  @bentoml.Runnable.method(batchable=False)
  async def generate_iterator(self, prompt_token_ids, request_id, stop=None, adapter_name=None, **attrs):
    if adapter_name is not None:
      self.model.set_adapter(adapter_name)
    async for generation_output in self.forward(prompt_token_ids, request_id, stop=stop, **attrs):
      yield generation_output.model_dump_json()

  async def forward(self, prompt_token_ids, request_id, stop=None, **attrs):
    from ._generation import is_partial_stop, prepare_logits_processor

    stop_: set[str] = set()
    if isinstance(stop, str) and stop != '':
      stop_.add(stop)
    elif isinstance(stop, t.Iterable):
      stop_.update(stop)
    config = self.config.model_construct_env(**attrs)

    with torch.inference_mode():
      # TODO: Support context_length check
      # context_length: int | None = attrs.pop('context_length', None)
      # if context_length is None: context_length = get_context_length(self.model.config)
      # max_src_len = context_length - config['max_new_tokens'] - 1
      # prompt_token_ids = prompt_token_ids[-max_src_len:]
      output_token_ids = list(prompt_token_ids)
      input_len = len(prompt_token_ids)

      logits_processor = prepare_logits_processor(config)

      past_key_values = out = token = None
      finish_reason = None
      for i in range(config['max_new_tokens']):
        if i == 0:  # prefill
          out = self.model(torch.as_tensor([prompt_token_ids], device=self.model.device), use_cache=True)
        else:  # decoding
          out = self.model(
            torch.as_tensor([[token]], device=self.model.device), use_cache=True, past_key_values=past_key_values
          )
        logits = out.logits
        past_key_values = out.past_key_values

        if logits_processor:
          if config['repetition_penalty'] > 1.0:
            tmp_output_ids: t.Any = torch.as_tensor([output_token_ids], device=self.model.device)
          else:
            tmp_output_ids = None
          last_token_logits = logits_processor(tmp_output_ids, logits[:, -1, :])[0]
        else:
          last_token_logits = logits[0, -1, :]

        # Switch to CPU by avoiding some bugs in mps backend.
        if self.model.device.type == 'mps':
          last_token_logits = last_token_logits.float().to('cpu')

        if config['temperature'] < 1e-5 or config['top_p'] < 1e-8:  # greedy
          _, indices = torch.topk(last_token_logits, 2)
          tokens = [int(index) for index in indices.tolist()]
        else:
          probs = torch.softmax(last_token_logits, dim=-1)
          indices = torch.multinomial(probs, num_samples=2)
          tokens = [int(token) for token in indices.tolist()]

        token = tokens[0]
        output_token_ids.append(token)

        stopped = False

        tmp_output_ids, rfind_start = output_token_ids[input_len:], 0
        # XXX: Move this to API server
        text = self.tokenizer.decode(
          tmp_output_ids,
          skip_special_tokens=True,
          spaces_between_special_tokens=False,
          clean_up_tokenization_spaces=True,
        )
        partially_stopped = False
        if stop_:
          for it in stop_:
            pos = text.rfind(it, rfind_start)
            if pos != -1:
              text, stopped = text[:pos], True
              break
            else:
              partially_stopped = is_partial_stop(text, it)
              if partially_stopped:
                break
        if not partially_stopped:
          yield GenerationOutput(
            prompt='',
            finished=False,
            outputs=[
              CompletionChunk(
                index=0, text=text, token_ids=output_token_ids[input_len:], cumulative_logprob=0.0, finish_reason=None
              )
            ],
            prompt_token_ids=prompt_token_ids,
            request_id=request_id,
          )
        if stopped:
          break
      else:
        finish_reason = 'length'
      if stopped:
        finish_reason = 'stop'
      yield GenerationOutput(
        prompt='',
        finished=True,
        outputs=[
          CompletionChunk(
            index=0,
            text=text,
            token_ids=output_token_ids[input_len:],
            cumulative_logprob=0.0,
            finish_reason=finish_reason,
          )
        ],
        prompt_token_ids=prompt_token_ids,
        request_id=request_id,
      )

    # Clean
    del past_key_values, out
    gc.collect()
    torch.cuda.empty_cache()
