"""Run a real Phase-2 call (BUILD Done-when item 2 + flag 2). Uses the real
config.toml + your key from ~/.config/research-room/secrets.json (chmod 600).

  # store a key once (write-only, outside the repo):
  python3 -c "from engine import secrets; secrets.set('deepseek','sk-...')"
  python3 -c "from engine import secrets; secrets.set('claude','sk-ant-...')"

  # then make the call:
  python3 tests/real_call.py deepseek    # cheapest — do first
  python3 tests/real_call.py claude      # the divergent content-blocks shape
"""

import sys

from engine import providers as P, secrets

key = sys.argv[1] if len(sys.argv) > 1 else "deepseek"
if not secrets.has_key(key):
    sys.exit(f"no key for '{key}'. Set it: "
             f"python3 -c \"from engine import secrets; secrets.set('{key}','<KEY>')\"")

payload = {"system": "You are terse.",
           "messages": [{"role": "user", "content": "Reply with exactly: ok"}]}
print(f"calling {key} ({P.provider(key).model}) …")
print("→", P.call_model(key, payload))
