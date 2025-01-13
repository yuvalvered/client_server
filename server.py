import socket
import struct
import threading
import time
import random
import sys
from typing import Tuple

# Network protocol constants
MAGIC_COOKIE = 0xabcddcba
MSG_TYPE_OFFER = 0x2
MSG_TYPE_REQUEST = 0x3
MSG_TYPE_PAYLOAD = 0x4
BROADCAST_PORT = 13117
BUFFER_SIZE = 1024
OFFER_INTERVAL = 1  # Seconds between offer broadcasts

# Server port settings
SERVER_TCP_PORT = 12345  # You can change this to your desired TCP port
SERVER_UDP_PORT = 12346  # You can change this to your desired UDP port


class SpeedTestServer:
    def __init__(self):
        """Initialize the speed test server with UDP and TCP sockets."""
        try:
            # Create UDP socket for broadcasting offers
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # Create TCP socket for handling file transfers
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.bind(('', SERVER_TCP_PORT))
            self.tcp_socket.listen(5)

            # Create UDP socket for handling speed test requests
            self.udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_server.bind(('', SERVER_UDP_PORT))

            # Store ports and IP
            self.server_ip = self._get_server_ip()
            self.tcp_port = SERVER_TCP_PORT
            self.udp_port = SERVER_UDP_PORT

            print(f"Server started, listening on IP address {self.server_ip}")
            print(f"TCP port: {self.tcp_port}, UDP port: {self.udp_port}")

        except Exception as e:
            print(f"Failed to initialize server: {e}")
            sys.exit(1)

    def _get_server_ip(self) -> str:
        """
        Get the server's IP address.

        Returns:
            str: Server's IP address
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def broadcast_offers(self):
        """Continuously broadcast offer messages."""
        while True:
            try:
                offer_message = struct.pack('!IbHH',
                                            MAGIC_COOKIE,
                                            MSG_TYPE_OFFER,
                                            self.udp_port,
                                            self.tcp_port
                                            )

                self.udp_socket.sendto(offer_message, ('<broadcast>', BROADCAST_PORT))
                time.sleep(OFFER_INTERVAL)

            except Exception as e:
                print(f"Error broadcasting offer: {e}")

    def handle_tcp_transfer(self, client_socket: socket.socket, client_address: Tuple[str, int]):
        """
        Handle TCP file transfer request.

        Args:
            client_socket: Connected client socket
            client_address: Client's address tuple (ip, port)
        """
        try:
            print(f"New TCP connection from {client_address[0]}:{client_address[1]}")

            request = client_socket.recv(BUFFER_SIZE).decode()
            if not request.strip():
                return

            file_size = int(request.strip())
            print(f"TCP request from {client_address[0]}: {file_size} bytes")

            bytes_sent = 0
            chunk_size = min(BUFFER_SIZE, file_size)

            while bytes_sent < file_size:
                remaining = file_size - bytes_sent
                current_chunk = min(chunk_size, remaining)
                data = random.randbytes(current_chunk)
                client_socket.send(data)
                bytes_sent += current_chunk

            print(f"TCP transfer to {client_address[0]} completed: {bytes_sent} bytes")

        except Exception as e:
            print(f"Error in TCP transfer to {client_address[0]}: {e}")

        finally:
            client_socket.close()

    def handle_udp_transfer(self, request_data: bytes, client_address: Tuple[str, int]):
        """
        Handle UDP file transfer request.

        Args:
            request_data: Raw request data
            client_address: Client's address tuple (ip, port)
        """
        try:
            # Parse request
            magic_cookie, msg_type, file_size = struct.unpack('!IbQ', request_data)

            if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_REQUEST:
                return

            print(f"UDP request from {client_address[0]}: {file_size} bytes")

            # Calculate total segments
            segment_size = BUFFER_SIZE - 21  # Account for header size
            total_segments = (file_size + segment_size - 1) // segment_size

            # Send data in segments
            bytes_sent = 0
            segment_num = 0

            while bytes_sent < file_size:
                remaining = file_size - bytes_sent
                current_size = min(segment_size, remaining)
                payload = random.randbytes(current_size)

                # Create packet with header
                packet = struct.pack('!IbQQ',
                                     MAGIC_COOKIE,
                                     MSG_TYPE_PAYLOAD,
                                     total_segments,
                                     segment_num
                                     ) + payload

                self.udp_server.sendto(packet, client_address)
                bytes_sent += current_size
                segment_num += 1

                # Small delay to prevent overwhelming the network
                time.sleep(0.001)

            print(f"UDP transfer to {client_address[0]} completed: {bytes_sent} bytes in {segment_num} segments")

        except Exception as e:
            print(f"Error in UDP transfer to {client_address[0]}: {e}")

    def run(self):
        """Start the server and handle incoming connections."""
        try:
            # Start broadcast thread
            broadcast_thread = threading.Thread(target=self.broadcast_offers, daemon=True)
            broadcast_thread.start()

            # Create threads for handling TCP and UDP connections
            tcp_thread = threading.Thread(target=self.handle_tcp_connections, daemon=True)
            udp_thread = threading.Thread(target=self.handle_udp_connections, daemon=True)

            tcp_thread.start()
            udp_thread.start()

            # Keep the main thread alive
            tcp_thread.join()

        except KeyboardInterrupt:
            print("\nServer shutting down...")
            sys.exit(0)

        except Exception as e:
            print(f"Error in server operation: {e}")
            sys.exit(1)

    def handle_tcp_connections(self):
        """Accept and handle TCP connections."""
        while True:
            try:
                client_socket, client_address = self.tcp_socket.accept()
                thread = threading.Thread(
                    target=self.handle_tcp_transfer,
                    args=(client_socket, client_address),
                    daemon=True
                )
                thread.start()

            except Exception as e:
                print(f"Error accepting TCP connection: {e}")

    def handle_udp_connections(self):
        """Handle incoming UDP requests."""
        while True:
            try:
                data, addr = self.udp_server.recvfrom(BUFFER_SIZE)
                thread = threading.Thread(
                    target=self.handle_udp_transfer,
                    args=(data, addr),
                    daemon=True
                )
                thread.start()

            except Exception as e:
                print(f"Error handling UDP request: {e}")


if __name__ == "__main__":
    try:
        server = SpeedTestServer()
        server.run()
    except KeyboardInterrupt:
        print("\nServer shutting down...")
        sys.exit(0)