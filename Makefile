.PHONY: fonts fonts-check docs serve

# Vendored webfonts. Renovate moves the pins in scripts/update-fonts.sh; the
# binaries it cannot write come from running this on the branch.
fonts:
	scripts/update-fonts.sh

fonts-check:
	scripts/update-fonts.sh --check

docs:
	uv run zensical build --clean --strict

serve:
	uv run zensical serve
