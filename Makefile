COMPOSE ?= docker compose

.PHONY: up up-d build down restart logs logs-core logs-bot logs-web ps config pull clean rebuild-core rebuild-bot rebuild-web

up:
	$(COMPOSE) up --build

up-d:
	$(COMPOSE) up --build -d

build:
	$(COMPOSE) build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down
	$(COMPOSE) up --build -d

logs:
	$(COMPOSE) logs -f

logs-core:
	$(COMPOSE) logs -f jingxia-core

logs-bot:
	$(COMPOSE) logs -f jingxia-bot

logs-web:
	$(COMPOSE) logs -f jingxia-web

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config

pull:
	$(COMPOSE) pull

rebuild-core:
	$(COMPOSE) build jingxia-core
	$(COMPOSE) up -d jingxia-core

rebuild-bot:
	$(COMPOSE) build jingxia-bot
	$(COMPOSE) up -d jingxia-bot

rebuild-web:
	$(COMPOSE) build jingxia-web
	$(COMPOSE) up -d jingxia-web

clean:
	$(COMPOSE) down --remove-orphans
