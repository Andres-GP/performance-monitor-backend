#!/usr/bin/env python3
import asyncio
import json
import websockets

async def fake_bridge():
    uri = "ws://localhost:9001"
    async with websockets.connect(uri) as websocket:
        # Enviar autenticación
        await websocket.send(json.dumps({
            "type": "auth",
            "token": "",  # cámbialo por tu API_SECRET_KEY
            "platform": "SIMULATED_BRIDGE"
        }))
        response = await websocket.recv()
        print(f"Auth response: {response}")
        
        # Escuchar órdenes entrantes
        async for message in websocket:
            data = json.loads(message)
            print(f"Received order: {data}")
            if data.get("type") == "execute_order":
                # Simular ejecución
                await websocket.send(json.dumps({
                    "type": "order_update",
                    "status": "filled",
                    "order": data["order"]
                }))

if __name__ == "__main__":
    asyncio.run(fake_bridge())