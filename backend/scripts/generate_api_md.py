"""Generate docs/API.md endpoint reference from FastAPI OpenAPI schema."""

import os
import sys

# Ensure backend root is on PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app


def generate_endpoint_docs() -> str:
    schema = app.openapi()
    paths = schema.get("paths", {})

    by_tag: dict[str, list[dict]] = {}
    for path, methods in sorted(paths.items()):
        for method, spec in methods.items():
            if method.lower() not in ["get", "post", "put", "patch", "delete"]:
                continue
            tag = (spec.get("tags") or ["Other"])[0]
            by_tag.setdefault(tag, []).append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": spec.get("summary", ""),
                    "responses": list(spec.get("responses", {}).keys()),
                }
            )

    output = []
    output.append(f"Total API Endpoints: {sum(len(items) for items in by_tag.values())}\n")
    for tag, items in sorted(by_tag.items()):
        output.append(f"### {tag} ({len(items)} endpoints)\n")
        output.append("| Method | Endpoint | Summary | Expected Responses |")
        output.append("|---|---|---|---|")
        for item in items:
            m = item["method"]
            p = item["path"]
            s = item["summary"]
            resps = ", ".join(item["responses"])
            output.append(f"| `{m}` | `{p}` | {s} | {resps} |")
        output.append("\n")

    return "\n".join(output)


def update_docs_api_md():
    docs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "docs",
        "API.md",
    )
    with open(docs_path, encoding="utf-8") as f:
        content = f.read()

    # Locate "## Endpoints"
    header = "## Endpoints\n"
    if header in content:
        base_content = content.split(header)[0] + header
    else:
        base_content = content + "\n\n" + header

    new_content = base_content + "\n" + generate_endpoint_docs()
    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Updated {docs_path} successfully.")


if __name__ == "__main__":
    update_docs_api_md()
