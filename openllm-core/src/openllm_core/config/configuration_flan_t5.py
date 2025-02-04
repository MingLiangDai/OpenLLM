from __future__ import annotations
import typing as t

import openllm_core
from openllm_core.prompts import PromptTemplate, process_prompt

DEFAULT_PROMPT_TEMPLATE = """Answer the following question:\nQuestion: {instruction}\nAnswer:"""


class FlanT5Config(openllm_core.LLMConfig):
  """FLAN-T5 was released in the paper [Scaling Instruction-Finetuned Language Models](https://arxiv.org/pdf/2210.11416.pdf).

  It is an enhanced version of T5 that has been finetuned in a mixture of tasks.

  Refer to [FLAN-T5's page](https://huggingface.co/docs/transformers/model_doc/flan-t5) for more information.
  """

  __config__ = {
    'url': 'https://huggingface.co/docs/transformers/model_doc/flan-t5',
    'architecture': 'T5ForConditionalGeneration',
    'model_type': 'seq2seq_lm',
    'backend': ('pt',),
    # NOTE: See https://www.philschmid.de/fine-tune-flan-t5. No specific template found, but seems to have the same dialogue style
    'default_id': 'google/flan-t5-large',
    'model_ids': [
      'google/flan-t5-small',
      'google/flan-t5-base',
      'google/flan-t5-large',
      'google/flan-t5-xl',
      'google/flan-t5-xxl',
    ],
  }

  class GenerationConfig:
    temperature: float = 0.9
    max_new_tokens: int = 2048
    top_k: int = 50
    top_p: float = 0.4
    repetition_penalty = 1.0

  def sanitize_parameters(
    self,
    prompt: str,
    prompt_template: PromptTemplate | str | None = None,
    system_message: str | None = None,
    max_new_tokens: int | None = None,
    temperature: float | None = None,
    top_k: int | None = None,
    top_p: float | None = None,
    repetition_penalty: float | None = None,
    use_default_prompt_template: bool = True,
    **attrs: t.Any,
  ) -> tuple[str, dict[str, t.Any], dict[str, t.Any]]:
    return (
      process_prompt(prompt, DEFAULT_PROMPT_TEMPLATE, use_default_prompt_template, **attrs),
      {
        'max_new_tokens': max_new_tokens,
        'temperature': temperature,
        'top_k': top_k,
        'top_p': top_p,
        'repetition_penalty': repetition_penalty,
      },
      {},
    )
