# TCP Chat Project

A dependency-free Python TCP chat project with a multi-threaded server and matching client.

Features:

- one thread per connected client
- `/list`, `/dm`, `/rename`, `/help`, `/history`, `/stats`, and `/quit`
- timestamps on chat messages
- public message history
- server-side logging
- per-client rate limiting
- graceful shutdown on `Ctrl+C`

## Run the Server

```bash
python server.py --host 127.0.0.1 --port 5000
```

## Run a Client

Open a second terminal:

```bash
python client.py --host 127.0.0.1 --port 5000 --name alice
```

Open another terminal for a second user:

```bash
python client.py --host 127.0.0.1 --port 5000 --name bob
```

## Commands

```text
/list                 Show connected users
/dm <user> <message>  Send a private message
/rename <name>        Change your display name
/history [count]      Show recent public chat history
/stats                Show server statistics
/help                 Show command help
/quit                 Disconnect
```

## Test

```bash
python -B -m unittest discover -s tests
```

## Install as Console Scripts

```bash
python -m pip install -e .
chat-server --port 5000
chat-client --name alice
```
