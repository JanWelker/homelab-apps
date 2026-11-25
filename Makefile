.PHONY: fonts fonts-check docs serve render dry-run-input dry-run

# A checkout of the platform repository at main, for the server dry run.
HOMELAB ?= ../homelab

# Vendored webfonts. Renovate moves the pins in scripts/update-fonts.sh; the
# binaries it cannot write come from running this on the branch.
fonts:
	scripts/update-fonts.sh

fonts-check:
	scripts/update-fonts.sh --check

# What CI renders: every Application, each chart with its values from an
# empty directory so helm cannot mistake an application directory for a
# chart. Not under .cache/, which `zensical build --clean` empties.
render:
	uv run scripts/render-charts.py --out output/rendered

# What the Server Dry Run workflow sends: this render plus the platform's
# CRDs, admission policies and namespaces, rendered by the platform's script.
dry-run-input: render
	uv run --project $(HOMELAB) $(HOMELAB)/scripts/render-charts.py --out output/platform
	rm -rf output/dry-run && cp -R output/rendered output/dry-run
	uv run scripts/platform-prerequisites.py output/platform output/dry-run

# Against the current kubeconfig context, which must be a kind-* cluster.
dry-run: dry-run-input
	uv run --project $(HOMELAB) $(HOMELAB)/scripts/server-dry-run.py output/dry-run

docs:
	uv run zensical build --clean --strict

serve:
	uv run zensical serve
