.PHONY: bootstrap doctor smoke-test test-collect e2e recovery-drill release-gate start init stack-up stack-down stack-ps stack-logs

bootstrap:
	./scripts/bootstrap_dev.sh

start:
	./.venv/bin/python -m beekeeper.cli.main start --build

init:
	./.venv/bin/python -m beekeeper.cli.main init

stack-up:
	./.venv/bin/python -m beekeeper.cli.main stack up --build

stack-down:
	./.venv/bin/python -m beekeeper.cli.main stack down

stack-ps:
	./.venv/bin/python -m beekeeper.cli.main stack ps

stack-logs:
	./.venv/bin/python -m beekeeper.cli.main stack logs queen-api

doctor:
	python -m beekeeper.runner doctor --json

smoke-test:
	python -m beekeeper.runner smoke-test --json

test-collect:
	pytest --collect-only -q

e2e:
	./scripts/run_e2e.sh

recovery-drill:
	./scripts/run_recovery_drill.sh

release-gate:
	./scripts/release_gate.sh
