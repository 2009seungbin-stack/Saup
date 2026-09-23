.PHONY: test check dev demo

test:
	python -m pytest -q

check:
	python -m compileall -q apps packages scripts migrations
	python -m pytest --cov=packages --cov=apps/api --cov=apps/worker -q

dev:
	docker compose up --build

demo:
	python -m scripts.demo
