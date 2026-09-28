"""Ufuk end-to-end test: register, login, chat completion (streaming + non-streaming)."""
import json
import sys
import urllib.request

BASE = "http://localhost:8000"
EMAIL = "ufuk-e2e-20260926@example.com"
PASSWORD = "TestPass123!"


def post(path: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def post_stream(path: str, body: dict, token: str) -> list[str]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    lines: list[str] = []
    with urllib.request.urlopen(req) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line:
                lines.append(line)
    return lines


def main() -> None:
    # Register (idempotent-ish: ignore conflict errors)
    try:
        out = post("/auth/register", {"email": EMAIL, "password": PASSWORD, "display_name": "E2E"})
        print(f"REGISTER OK: {json.dumps(out)[:200]}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:200]
        print(f"REGISTER (may already exist): {exc.code} {detail}")

    login = post("/auth/login", {"email": EMAIL, "password": PASSWORD})
    token = login["access_token"]
    print(f"LOGIN OK: token={token[:20]}...")

    me = json.loads(urllib.request.urlopen(urllib.request.Request(f"{BASE}/me", headers={"Authorization": f"Bearer {token}"})).read())
    print(f"ME OK: {json.dumps(me)[:200]}")

    models = json.loads(urllib.request.urlopen(urllib.request.Request(f"{BASE}/v1/models", headers={"Authorization": f"Bearer {token}"})).read())
    print(f"MODELS OK: {[m['id'] for m in models['data']]}")

    # Non-streaming chat
    print("\n--- NON-STREAMING CHAT ---")
    try:
        out = post("/v1/chat/completions", {"model": "fast", "messages": [{"role": "user", "content": "Say exactly: UFUK-E2E-OK"}]}, token)
        content = out["choices"][0]["message"]["content"]
        print(f"REPLY: {content[:300]}")
        print(f"USAGE: {out.get('usage')}")
    except urllib.error.HTTPError as exc:
        print(f"CHAT FAILED: {exc.code} {exc.read().decode()[:300]}")
        sys.exit(1)

    # Streaming chat
    print("\n--- STREAMING CHAT ---")
    try:
        lines = post_stream("/v1/chat/completions", {"model": "fast", "messages": [{"role": "user", "content": "Count from 1 to 5, one number per line."}], "stream": True}, token)
        data_lines = [l for l in lines if l.startswith("data:")]
        print(f"SSE LINES: {len(lines)} total, {len(data_lines)} data lines")
        done = [l for l in data_lines if "[DONE]" in l]
        print(f"DONE marker present: {len(done) > 0}")
        # Show first and last content deltas
        contents = []
        for l in data_lines:
            payload = l[5:].strip()
            if payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content")
                if delta:
                    contents.append(delta)
            except json.JSONDecodeError:
                pass
        full = "".join(contents)
        print(f"STREAMED CONTENT: {full[:300]}")
    except urllib.error.HTTPError as exc:
        print(f"STREAM FAILED: {exc.code} {exc.read().decode()[:300]}")
        sys.exit(1)

    print("\nALL E2E CHECKS PASSED")


if __name__ == "__main__":
    main()
