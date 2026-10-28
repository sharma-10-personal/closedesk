"""Placeholder generator. Real plant-and-key logic lands Thursday."""

from pathlib import Path


def main() -> None:
    out = Path("data")
    out.mkdir(exist_ok=True)
    (out / ".gitkeep").write_text("Run the generator implementation to fill this folder.\n")
    print("Generator not implemented yet. data/ created.")


if __name__ == "__main__":
    main()
