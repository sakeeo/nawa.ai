import argparse
import os

from noesantara_seed.load import load


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Resto Noesantara demo data.")
    parser.add_argument("--url", default=os.environ.get("NOESANTARA_DATABASE_URL"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.url:
        parser.error("set --url or NOESANTARA_DATABASE_URL")
    for table, count in load(args.url, args.seed).items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
