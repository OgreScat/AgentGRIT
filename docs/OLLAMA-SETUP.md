# Ollama Setup for AgentGRIT

**Optional local LLM for FREE routing of simple tasks.**

Ollama is the cost-first default for simple tasks. It's optional - AgentGRIT works without it, but you'll route more tasks to paid providers.

---

## Installation

### macOS (Homebrew)

```bash
brew install ollama
```

### macOS (Direct Download)

Download from https://ollama.ai and run the installer.

### Verify Installation

```bash
ollama --version
```

---

## Pull a Model

AgentGRIT defaults to `qwen3-coder:30b` for coding tasks. Choose based on your RAM:

| Model | RAM Required | Quality |
|-------|--------------|---------|
| `qwen2.5-coder:7b` | 8GB | Good |
| `qwen3-coder:14b` | 16GB | Better |
| `qwen3-coder:30b` | 32GB+ | Best |

```bash
# For Apple Silicon with 32GB+ RAM
ollama pull qwen3-coder:30b

# For 16GB machines
ollama pull qwen3-coder:14b

# For 8GB machines
ollama pull qwen2.5-coder:7b
```

---

## Start Ollama Server

```bash
ollama serve
```

This starts the API on `http://localhost:11434`.

**Tip:** Run in a separate terminal or background it:

```bash
ollama serve &
```

---

## Healthcheck

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

Expected output:

```json
{"models":[{"name":"qwen3-coder:30b",...}]}
```

---

## Smoke Test (One Task)

Test that AgentGRIT routes simple tasks to Ollama:

### Quick Test

```bash
cd /path/to/AgentGRIT
python -c "
import asyncio
from src.execution.router import LLMRouter

async def test():
    router = LLMRouter({'ollama_model': 'qwen3-coder:30b'})
    result = await router.execute('Explain what a Python list comprehension is')
    print(f'Provider: {result[\"provider\"]}')
    print(f'Cost: \${result[\"cost\"]:.4f}')
    print(f'Response: {result[\"response\"][:200]}...')

asyncio.run(test())
"
```

Expected output:

```
Provider: ollama
Cost: $0.0000
Response: A Python list comprehension is a concise way to create lists...
```

### Verify Routing Logic

```bash
cd /path/to/AgentGRIT
python -c "
from src.execution.router import LLMRouter

router = LLMRouter()
tasks = [
    'Format this Python code nicely',
    'Explain how async/await works',
    'Research latest FastAPI release notes',
]

for task in tasks:
    decision = router.route_with_evidence(task)
    print(f'{task[:40]:<40} → {decision.provider}')
"
```

Expected output:

```
Format this Python code nicely           → ollama
Explain how async/await works            → ollama
Research latest FastAPI release notes    → perplexity
```

---

## Configuration

Set the Ollama model in your environment or config:

```bash
# In .env
OLLAMA_MODEL=qwen3-coder:30b
OLLAMA_HOST=http://localhost:11434
```

Or pass directly to the router:

```python
router = LLMRouter({
    'ollama_model': 'qwen3-coder:30b',
    'ollama_host': 'http://localhost:11434',
})
```

---

## Troubleshooting

### "Connection refused"

Ollama server isn't running:

```bash
ollama serve
```

### Model not found

Pull the model first:

```bash
ollama pull qwen3-coder:30b
```

### Slow responses

- Use a smaller model (`qwen2.5-coder:7b`)
- Close other memory-intensive apps
- Check Activity Monitor for memory pressure

### Still routes to Claude

Check your task classification:

```python
from src.execution.router import classify_task

result = classify_task("your task here")
print(result.category, result.required_capabilities)
```

If capabilities include `web_search`, `real_time_social`, or `complex_architecture`, it won't go to Ollama.

---

## Without Ollama

AgentGRIT works without Ollama - it will route simple tasks to the next available provider:

1. If Ollama unavailable → Perplexity
2. If Perplexity budget exhausted → Grok
3. If all else fails → Claude

The router handles this automatically based on `PROVIDER_CAPABILITIES`.

---

## Cost Savings

With Ollama handling simple tasks:

```
Task: "Format this code"
  Without Ollama: Perplexity $0.001 or Claude $0.003
  With Ollama: $0.00

Estimated monthly savings (100 simple tasks/day):
  3000 tasks × $0.001 = $3.00 → $0.00
```

Free is better than cheap.
