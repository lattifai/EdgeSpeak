"""List the live model catalog by capability without loading or downloading models.

Set EDGESPEAK_API_KEY for an owned CLI, or --base-url and optional
EDGESPEAK_GATEWAY_KEY for an existing gateway."""
import argparse
import json
import os
import asyncio
from edgespeak import AsyncEdgeSpeak

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Attach to an existing gateway")
    parser.add_argument("--json", action="store_true", help="Print all model metadata as JSON")
    args = parser.parse_args()
    async with AsyncEdgeSpeak(
        base_url=args.base_url,
        gateway_key=os.environ.get("EDGESPEAK_GATEWAY_KEY") if args.base_url else None,
    ) as client:
        catalog = await client.models()
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return
    groups = catalog["groups"]
    if not groups:
        print("The gateway returned no models.")
    for capability, group in groups.items():
        print(f"\n{group['title']} ({capability})")
        print(group['description'])
        for model in group['models']:
            state = {True: "installed", False: "not installed"}.get(model.get("installed"), "installation unknown")
            defaults = ", ".join(model.get("default_for", [])) or "none advertised"
            print(f"  {model['id']} | {state} | default for: {defaults}")
            print("    endpoints: " + ", ".join(model.get("supported_endpoints", [])))

if __name__ == "__main__":
    asyncio.run(main())
