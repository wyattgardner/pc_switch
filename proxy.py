# Used to forward pc_switch_app packets to the microcontroller(s) from a device on the same LAN

import asyncio
import logging

# Local Port : (Target IP, Target Port)
FORWARD_MAPPING = {
    7776: ('192.168.1.100', 7776),
    7775: ('192.168.1.101', 7775),
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

async def forward_data(reader, writer, tag):
    """
    Reads from 'reader' and writes to 'writer' until the connection closes.
    """
    try:
        while True:
            # Read data in chunks
            data = await reader.read(4096)
            if not data:
                break # Connection closed
            
            writer.write(data)
            await writer.drain()
    except Exception as e:
        # Connection reset or broken pipe is common, usually safe to ignore in simple proxy
        pass
    finally:
        # Close the writer when reading is done
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_client(local_reader, local_writer, target_host, target_port):
    """
    Handles a single incoming connection.
    Opens a connection to the target and pipes data both ways.
    """
    peer_addr = local_writer.get_extra_info('peername')
    logging.info(f"New connection from {peer_addr} -> Forwarding to {target_host}:{target_port}")

    try:
        # Connect to the remote target
        remote_reader, remote_writer = await asyncio.open_connection(target_host, target_port)
    except Exception as e:
        logging.error(f"Failed to connect to target {target_host}:{target_port} - {e}")
        local_writer.close()
        return

    # Create two tasks:
    # 1. Pipe data from Local Client -> Remote Target
    # 2. Pipe data from Remote Target -> Local Client
    task1 = asyncio.create_task(forward_data(local_reader, remote_writer, "C->S"))
    task2 = asyncio.create_task(forward_data(remote_reader, local_writer, "S->C"))

    # Wait for both pipes to finish (when one side closes connection)
    await asyncio.gather(task1, task2)
    
    logging.info(f"Connection closed: {peer_addr}")

async def start_forwarding_server(local_port, target_host, target_port):
    """
    Starts a listener on the local port.
    """
    # We use a lambda or partial to pass the specific target info to the handler
    handler = lambda r, w: handle_client(r, w, target_host, target_port)
    
    server = await asyncio.start_server(handler, '0.0.0.0', local_port)
    
    logging.info(f"Listening on 0.0.0.0:{local_port} -> {target_host}:{target_port}")
    
    async with server:
        await server.serve_forever()

async def main():
    tasks = []
    
    # Create a server task for each mapping defined at the top
    for local_port, (target_host, target_port) in FORWARD_MAPPING.items():
        tasks.append(
            start_forwarding_server(local_port, target_host, target_port)
        )
    
    # Run all servers concurrently
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping proxy servers...")