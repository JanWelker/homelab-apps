.PHONY: fonts fonts-check docs serve render

# Vendored webfonts. Renovate moves the pins in scripts/update-fonts.sh; the
# binaries it cannot write come from running this on the branch.
fonts:
	scripts/update-fonts.sh

fonts-check:
	scripts/update-fonts.sh --check

# What CI renders: every chart-based Application with its values, from an
# empty directory so helm cannot mistake an application directory for a chart.
render:
	uv run scripts/render-charts.py --out .cache/rendered

docs:
	uv run zensical build --clean --strict

serve:
	uv run zensical serve
