import os
import sys
from dotenv import load_dotenv
from src.api_client import YouTubeAPIClient
from src.config import CHANNELS_TO_RESOLVE

def main():
    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("ERROR: YOUTUBE_API_KEY environment variable is not set in .env", file=sys.stderr)
        sys.exit(1)

    print("Initializing YouTube API Client...")
    client = YouTubeAPIClient(api_key=api_key)

    resolved = {}
    has_errors = False

    print("\nResolving target channels:")
    print("-" * 40)
    for target in CHANNELS_TO_RESOLVE:
        try:
            print(f"Resolving '{target}'...")
            channel_id = client.resolve_channel_id(target)
            resolved[target] = channel_id
            print(f"  -> SUCCESS: {channel_id}")
        except Exception as e:
            print(f"  -> FAILED: {e}", file=sys.stderr)
            has_errors = True

    print("-" * 40)
    if has_errors:
        print("\nSome channels failed to resolve. Please check logs and try again.", file=sys.stderr)
        sys.exit(1)

    print("\nAll channels resolved successfully! Add this to src/config.py:\n")
    print("RESOLVED_CHANNELS = {")
    for name, cid in resolved.items():
        print(f"    {repr(name)}: {repr(cid)},")
    print("}")

if __name__ == "__main__":
    main()
