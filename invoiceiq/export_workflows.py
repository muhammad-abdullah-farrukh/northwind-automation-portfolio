"""Export the InvoiceIQ workflows from the local n8n container into invoiceiq/workflows/.

Keeps only what is needed to import a workflow (name, nodes, connections, settings) and strips
instance metadata: the owner's project and sharing (which carry the owner's name and email),
version history and the Gmail trigger's saved poll state. Credentials stay referenced by name and id.

Usage (from the repo root, with the n8n container running):
    python invoiceiq/export_workflows.py
"""

import json
import subprocess
from pathlib import Path

WORKFLOWS = {
    "8Z4oSoMQupFhcOwK": "1_intake",
    "D9nN9vOhnGkx79En": "2_process_invoice",
    "o00uRb21QVfbgsh9": "3_error_handler",
    "CF7IK518OBop0oah": "4_finance_agent",
    "Ux3mcrLGWgGWvFQS": "4a_safe_sql_tool",
}
OUT = Path(__file__).resolve().parent / "workflows"
KEEP = ("name", "nodes", "connections", "settings")
FORBIDDEN = ["xoxb-"]  # Slack tokens must never land in the repo
# Personal email fragments are checked too, but they are kept in a git-ignored file so the guard does not publish them itself.
PRIVATE_FRAGMENTS = Path(__file__).resolve().parent / ".secrets" / "forbidden_fragments.txt"
if PRIVATE_FRAGMENTS.exists():
    FORBIDDEN += [s.strip() for s in PRIVATE_FRAGMENTS.read_text(encoding="utf-8").splitlines() if s.strip()]


def export(workflow_id: str) -> dict:
    raw = subprocess.run(["docker", "exec", "n8n", "n8n", "export:workflow", f"--id={workflow_id}"],
                         check=True, capture_output=True, text=True, encoding="utf-8").stdout  # fmt: skip
    data = json.loads(raw[raw.index("["):])
    wf = data[0] if isinstance(data, list) else data
    return {k: wf[k] for k in KEEP if k in wf} | {"pinData": {}, "meta": {}, "tags": []}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for workflow_id, name in WORKFLOWS.items():
        text = json.dumps(export(workflow_id), indent=2, ensure_ascii=False) + "\n"
        leaked = [f for f in FORBIDDEN if f in text]
        if leaked:
            raise SystemExit(f"{name}: refusing to write, found {leaked}")
        (OUT / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"{name}.json  {len(json.loads(text)['nodes'])} nodes")


if __name__ == "__main__":
    main()
