import os
from pathlib import Path
from dotenv import dotenv_values

import ollama

from src.errors import ModelUnavailableError

DEFAULT_MODEL = 'qwen3:4b-instruct-2507-q4_K_M'

def setting(name, default):
    if name in os.environ:
        return os.environ[name] or default
    return dotenv_values(Path(__file__).resolve().parents[2] / '.env').get(name) or default


def create_client(*, timeout=None):
    return ollama.Client(
        host=setting("OLLAMA_HOST", "http://127.0.0.1:11434"),
        timeout=timeout if timeout is not None else float(setting("OLLAMA_TIMEOUT", "300")),
        trust_env=False,
    )


def generate_text(client, model, prompt, *, system="", context_tokens=4096, output_tokens=512, response_format=None):
    try:
        batch_size = int(setting('OLLAMA_BATCH_SIZE', '128'))
        if not 1 <= batch_size <= 512:
            raise ValueError('OLLAMA_BATCH_SIZE must be between 1 and 512.')
        options = {"num_ctx": context_tokens, "num_predict": output_tokens, "num_batch": batch_size, "temperature": 0.1}
        gpu_layers = setting('OLLAMA_GPU_LAYERS', '')
        if gpu_layers:
            layers = int(gpu_layers)
            if not -1 <= layers <= 999:
                raise ValueError('OLLAMA_GPU_LAYERS must be between -1 and 999.')
            options['num_gpu'] = layers
        response = client.generate(
            model=model, prompt=prompt, system=system, stream=False,
            keep_alive=setting('OLLAMA_KEEP_ALIVE', '15m'),
            options=options,
            **({"format": response_format} if response_format is not None else {}),
        )
        text = response.get("response", "").strip()
        if not text:
            raise ModelUnavailableError("The local model returned an empty response.")
        return text
    except ModelUnavailableError:
        raise
    except Exception as exc:
        raise ModelUnavailableError("The local model is unavailable. Check that Ollama and the configured model are running.") from exc
