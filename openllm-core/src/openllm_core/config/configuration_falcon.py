from __future__ import annotations
import typing as t

import openllm_core
from openllm_core.prompts import PromptTemplate, process_prompt

DEFAULT_PROMPT_TEMPLATE = """{context}
{user_name}: {instruction}
{agent}:
"""


class FalconConfig(openllm_core.LLMConfig):
  """Falcon-7B is a 7B parameters causal decoder-only model built by TII and trained on 1,500B tokens of [RefinedWeb](https://huggingface.co/datasets/tiiuae/falcon-refinedweb) enhanced with curated corpora.

  It is made available under the TII Falcon LLM License.

  Refer to [Falcon's HuggingFace page](https://huggingface.co/tiiuae/falcon-7b) for more information.
  """

  __config__ = {
    'name_type': 'lowercase',
    'trust_remote_code': False,
    'timeout': int(36e6),
    'url': 'https://falconllm.tii.ae/',
    'requirements': ['einops', 'xformers'],
    'architecture': 'FalconForCausalLM',
    # NOTE: See https://huggingface.co/tiiuae/falcon-7b-instruct/discussions/1
    'default_id': 'tiiuae/falcon-7b',
    'model_ids': ['tiiuae/falcon-7b', 'tiiuae/falcon-40b', 'tiiuae/falcon-7b-instruct', 'tiiuae/falcon-40b-instruct'],
    'fine_tune_strategies': (
      {
        'adapter_type': 'lora',
        'r': 64,
        'lora_alpha': 16,
        'lora_dropout': 0.1,
        'bias': 'none',
        'target_modules': ['query_key_value', 'dense', 'dense_h_to_4h', 'dense_4h_to_h'],
      },
    ),
  }

  class GenerationConfig:
    max_new_tokens: int = 200
    top_k: int = 10
    num_return_sequences: int = 1
    num_beams: int = 4

  def sanitize_parameters(
    self,
    prompt: str,
    prompt_template: PromptTemplate | str | None = None,
    system_message: str | None = None,
    max_new_tokens: int | None = None,
    top_k: int | None = None,
    num_return_sequences: int | None = None,
    eos_token_id: int | None = None,
    use_default_prompt_template: bool = False,
    **attrs: t.Any,
  ) -> tuple[str, dict[str, t.Any], dict[str, t.Any]]:
    return (
      process_prompt(prompt, DEFAULT_PROMPT_TEMPLATE, use_default_prompt_template, **attrs),
      {
        'max_new_tokens': max_new_tokens,
        'top_k': top_k,
        'num_return_sequences': num_return_sequences,
        'eos_token_id': eos_token_id,
        **attrs,
      },
      {},
    )
