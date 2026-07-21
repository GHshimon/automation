"""マルチ AI ルーター — 適材適所でプロバイダを使い分ける。

役割分担:
  - Grok (xAI)        : web_search / x_search 付きのニュース収集(リアルタイム情報)
  - Ollama (ローカル)  : 統合サマリーなど軽い処理。無料・データ非流出。未起動なら fast_model へ
  - grok-4.1-fast     : ローカル LLM 不在時の安価なフォールバック
  - Perplexity        : 週1回の引用付き深掘りレポート(任意)

API キーは環境変数 → macOS キーチェーンの順に探す:
  XAI_API_KEY         / キーチェーン service 名 "xai-api-key"
  PERPLEXITY_API_KEY  / キーチェーン service 名 "perplexity-api-key"
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
import json
import logging

log = logging.getLogger("daily_report")

XAI_BASE_URL = "https://api.x.ai/v1"
PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def get_secret(env_var: str, keychain_service: str) -> str | None:
    """環境変数、なければ macOS キーチェーンから取得する。"""
    value = os.environ.get(env_var)
    if value:
        return value
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", keychain_service],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # macOS 以外、またはキーチェーン未登録
    return None


class ProviderError(RuntimeError):
    pass


class Router:
    def __init__(self, provider_config: dict):
        self.cfg = provider_config
        self.xai_key = get_secret("XAI_API_KEY", "xai-api-key")
        self.pplx_key = get_secret("PERPLEXITY_API_KEY", "perplexity-api-key")
        self._xai_client = None
        self._pplx_client = None

    # ---------- Grok: ニュース収集(リアルタイム検索付き) ----------

    def _xai(self):
        if self._xai_client is None:
            if not self.xai_key:
                raise ProviderError(
                    "XAI_API_KEY が見つかりません。環境変数か、"
                    "`security add-generic-password -s xai-api-key -a $USER -w <KEY>` "
                    "でキーチェーンに登録してください。"
                )
            from openai import OpenAI
            self._xai_client = OpenAI(api_key=self.xai_key, base_url=XAI_BASE_URL)
        return self._xai_client

    def news_report(self, topic: dict, language: str, max_output_tokens: int = 8000) -> str:
        """Grok に web_search + x_search 付きでトピックのニュースセクションを書かせる。"""
        prompt = f"""あなたは業界アナリストです。以下のトピックについて、過去24時間の動向を{language}でレポートしてください。

トピック: {topic["name"]}
注目観点: {topic.get("focus", "重要ニュース全般")}

構成(Markdown、見出しは ### から開始):
### 主要ニュース(3〜6件、各2〜3文で背景と意味を説明)
### X 上の注目の議論(あれば。誰がどんな論点で話しているか)
### 今日の示唆(読者が取るべきアクションや注目ポイントを1〜2点)

ルール: 事実と観測を区別する。各ニュースには出典 URL を付ける。重要な動きがない場合は正直に「特筆すべき動きなし」と書く。出力全体を ``` などのコードフェンスで囲まず、そのまま Markdown 本文として書くこと。"""

        response = self._xai().responses.create(
            model=self.cfg.get("news_model", "grok-4.5"),
            input=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search"}, {"type": "x_search"}],
            max_output_tokens=max_output_tokens,
        )
        text = getattr(response, "output_text", None)
        if not text:
            raise ProviderError(f"Grok から空の応答 (topic={topic['name']})")
        return text.strip()

    # ---------- 統合サマリー: ローカル Ollama → grok-4.1-fast の順 ----------

    def summarize(self, combined_report: str, language: str) -> str:
        prompt = (
            f"以下は本日の業界ニュースレポート全文です。冒頭に置くエグゼクティブサマリーを"
            f"{language}で作成してください。最重要ポイントを箇条書き5点以内、"
            f"忙しい読者が30秒で全体を掴める密度で。\n\n---\n\n{combined_report}"
        )
        local_model = self.cfg.get("local_model")
        if local_model and self._ollama_available():
            try:
                return self._ollama_generate(local_model, prompt)
            except Exception as e:  # ローカル失敗はフォールバックで続行
                log.warning("Ollama での要約に失敗、fast_model へフォールバック: %s", e)
        response = self._xai().responses.create(
            model=self.cfg.get("fast_model", "grok-4.1-fast"),
            input=[{"role": "user", "content": prompt}],
        )
        return response.output_text.strip()

    def _ollama_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def _ollama_generate(self, model: str, prompt: str) -> str:
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
        text = body.get("response", "").strip()
        if not text:
            raise ProviderError("Ollama から空の応答")
        return text

    # ---------- Perplexity: 週次深掘り(任意) ----------

    def deep_research(self, query: str, language: str) -> str:
        if not self.pplx_key:
            raise ProviderError(
                "PERPLEXITY_API_KEY が見つかりません(deep_research.enabled: false にするか、"
                "キーチェーン service 名 perplexity-api-key で登録してください)。"
            )
        if self._pplx_client is None:
            from openai import OpenAI
            self._pplx_client = OpenAI(
                api_key=self.pplx_key, base_url=PERPLEXITY_BASE_URL, timeout=1800,
            )
        dr_cfg = self.cfg.get("deep_research", {})
        resp = self._pplx_client.chat.completions.create(
            model=dr_cfg.get("model", "sonar-deep-research"),
            messages=[{"role": "user", "content": f"{query}\n\n出力言語: {language}"}],
        )
        return resp.choices[0].message.content.strip()
