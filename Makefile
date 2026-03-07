.PHONY: bootstrap doctor smoke-test test-collect e2e recovery-drill release-gate

bootstrap:
	./scripts/bootstrap_dev.sh

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
