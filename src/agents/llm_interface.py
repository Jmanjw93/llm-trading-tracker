import json, random, re
from typing import List, Dict, Any, Optional

class BaseLLM:
    def generate(self, prompt: str, n_samples: int = 1, temperature: float = 0.7) -> List[Dict[str, Any]]:
        raise NotImplementedError

class MockLLM(BaseLLM):
    """
    A simple rule-based model so the pipeline can run offline.
    Heuristic sentiment from keywords; randomized confidence for diversity.
    """
    POS = ["beat","beats","upgrade","surge","record","growth","buyback","profit","raises guidance","strong"]
    NEG = ["miss","downgrade","lawsuit","probe","fraud","scandal","cuts guidance","weak","recall","layoff"]

    def generate(self, prompt: str, n_samples: int = 1, temperature: float = 0.7) -> List[Dict[str, Any]]:
        out = []
        news_block = self._extract_news(prompt).lower()
        pos_hits = sum(1 for w in self.POS if w in news_block)
        neg_hits = sum(1 for w in self.NEG if w in news_block)
        for _ in range(n_samples):
            rnd = random.random()
            if pos_hits > neg_hits:
                direction = "bullish"
                base_conf = 0.55 + 0.1 * min(3, pos_hits-neg_hits)
            elif neg_hits > pos_hits:
                direction = "bearish"
                base_conf = 0.55 + 0.1 * min(3, neg_hits-pos_hits)
            else:
                direction = "neutral"
                base_conf = 0.5
            # add randomness for 'uncertainty sampling'
            conf = min(0.99, max(0.01, base_conf + (rnd-0.5)*0.2*temperature))
            reason = f"Heuristic signal: pos={pos_hits}, neg={neg_hits}."
            out.append({"direction": direction, "confidence": conf, "reason": reason})
        return out

    @staticmethod
    def _extract_news(prompt: str) -> str:
        m = re.search(r"Today's News \(raw, may be empty\):\s+\"\"\"(.*?)\"\"\"", prompt, flags=re.S)
        return m.group(1) if m else ""

class FineTunedStubModel(BaseLLM):
    """
    Demonstrates a 'fine-tuned' behavior by biasing towards patterns learned from synthetic few-shot cues.
    Replace with actual PEFT/SFT/RLHF integration.
    """
    def __init__(self, bias: Optional[str] = None):
        self.bias = bias or "none"

    def generate(self, prompt: str, n_samples: int = 1, temperature: float = 0.7) -> List[Dict[str, Any]]:
        base = MockLLM().generate(prompt, n_samples, temperature)
        # simple biasing: if RSI<30 -> bullish tilt; if RSI>70 -> bearish tilt
        rsi_match = re.search(r"RSI_14: ([0-9\.]+)", prompt)
        rsi = float(rsi_match.group(1)) if rsi_match else 50.0
        for b in base:
            if rsi < 30 and b["direction"] != "bullish" and self.bias != "bearish_only":
                b["direction"] = "bullish"
                b["confidence"] = max(b["confidence"], 0.6)
                b["reason"] += " RSI<30 tilt."
            if rsi > 70 and b["direction"] != "bearish" and self.bias != "bullish_only":
                b["direction"] = "bearish"
                b["confidence"] = max(b["confidence"], 0.6)
                b["reason"] += " RSI>70 tilt."
        return base

class OpenAIModel(BaseLLM):
    def __init__(self, model_name: str = "gpt-4o-mini", api_key_env: str = "OPENAI_API_KEY"):
        self.model_name = model_name
        self.api_key_env = api_key_env
    def generate(self, prompt: str, n_samples: int = 1, temperature: float = 0.7) -> List[Dict[str, Any]]:
        raise NotImplementedError("Implement OpenAI API call here.")

class HFModel(BaseLLM):
    """
    Real local Transformers inference for an instruction-tuned causal LM.
    Loads once and is reused across predict_day calls. Defaults to a small
    instruct model that is realistic to run on a CPU; pass model_name= for
    anything larger if a GPU is available.
    """
    _JSON_RE = re.compile(r"\{.*?\}", re.S)

    def __init__(self,
                 model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
                 revision: Optional[str] = None,
                 device_map: str = "auto",
                 max_new_tokens: int = 128,
                 dtype: Optional[str] = None):
        """
        revision: a specific Hub commit SHA (or tag) to pin, rather than
        floating on whatever `model_name` currently resolves to. Matters for
        two reasons (see RESEARCH.md section 4): reproducibility, and being
        able to reason at all about whether a backtest window post-dates the
        model's training cutoff - you can't check a cutoff against a model
        that silently changes under you.
        """
        self.model_name = model_name
        self.revision = revision
        self.max_new_tokens = max_new_tokens
        self._tok = None
        self._model = None
        self._device_map = device_map
        self._dtype = dtype

    def _lazy_load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        torch_dtype = self._dtype
        if torch_dtype is None:
            torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        self._tok = AutoTokenizer.from_pretrained(self.model_name, revision=self.revision, use_fast=True)
        if self._tok.pad_token is None:
            self._tok.pad_token = self._tok.eos_token
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            revision=self.revision,
            device_map=self._device_map,
            torch_dtype=torch_dtype,
        )
        self._model.eval()

    def _post(self, text: str) -> Dict[str, Any]:
        m = self._JSON_RE.search(text)
        js = {"direction": "neutral", "confidence": 0.5, "reason": "parse-fallback"}
        if m:
            try:
                obj = json.loads(m.group(0))
                d = str(obj.get("direction", "neutral")).lower()
                c = float(obj.get("confidence", 0.5))
                r = obj.get("reason", "")
                if d not in ("bullish", "bearish", "neutral"):
                    d = "neutral"
                c = max(0.0, min(1.0, c))
                js = {"direction": d, "confidence": c, "reason": r}
            except Exception:
                pass
        return js

    def generate(self, prompt: str, n_samples: int = 1, temperature: float = 0.7) -> List[Dict[str, Any]]:
        import torch
        self._lazy_load()

        messages = [
            {"role": "system", "content": "You are a disciplined financial analyst. Respond with ONLY a single JSON object, no extra text."},
            {"role": "user", "content": prompt},
        ]
        chat_prompt = self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tok([chat_prompt] * max(1, n_samples), return_tensors="pt", padding=True)
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        do_sample = temperature is not None and temperature > 0.0
        with torch.no_grad():
            outs = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=do_sample,
                temperature=max(0.01, float(temperature)) if do_sample else None,
                top_p=0.95 if do_sample else None,
                pad_token_id=self._tok.pad_token_id,
            )

        prompt_len = inputs["input_ids"].shape[1]
        gen_tokens = outs[:, prompt_len:]
        texts = self._tok.batch_decode(gen_tokens, skip_special_tokens=True)
        return [self._post(t) for t in texts]
