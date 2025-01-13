import socket
import struct
import threading
import time
import sys
from typing import Tuple, List, Optional
from dataclasses import dataclass

# Network protocol constants
MAGIC_COOKIE = 0xabcddcba
MSG_TYPE_OFFER = 0x2
MSG_TYPE_REQUEST = 0x3
MSG_TYPE_PAYLOAD = 0x4
BROADCAST_PORT = 13117
BUFFER_SIZE = 1024

# Timeout settings
UDP_TIMEOUT = 1.0  # Seconds to wait for UDP packets
TCP_TIMEOUT = 5.0  # Seconds to wait for TCP connection


@dataclass
class TransferStats:
    """Statistics for a file transfer."""
    transfer_type: str  # "TCP" or "UDP"
    connection_num: int  # Connection identifier
    total_time: float  # Total transfer time in seconds
    speed: float  # Transfer speed in bits/second
    packets_received: Optional[float] = None  # Percentage of packets received (UDP only)


class SpeedTestClient:
    def __init__(self):
        """Initialize the speed test client."""
        try:
            # Create UDP socket for receiving broadcast offers
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.bind(('', BROADCAST_PORT))

            print("Client started, listening for offer requests...")
        except Exception as e:
            print(f"Failed to initialize client: {e}")
            sys.exit(1)

    def get_user_parameters(self) -> Tuple[int, int, int]:
        """
        Get test parameters from user input.

        Returns:
            Tuple containing (file_size, tcp_connections, udp_connections)
        """
        while True:
            try:
                print("Please enter test parameters:")
                file_size = int(input("File size (in bytes): "))
                tcp_connections = int(input("Number of TCP connections: "))
                udp_connections = int(input("Number of UDP connections: "))

                if file_size <= 0:
                    raise ValueError("File size must be positive")
                if tcp_connections < 0 or udp_connections < 0:
                    raise ValueError("Number of connections cannot be negative")
                if tcp_connections == 0 and udp_connections == 0:
                    raise ValueError("Must have at least one connection")

                return file_size, tcp_connections, udp_connections

            except ValueError as e:
                print(f"Invalid input: {str(e)}. Please try again.")

    def receive_offer(self) -> Tuple[str, int, int]:
        """
        Wait for and process server offer messages.

        Returns:
            Tuple containing (server_ip, udp_port, tcp_port)
        """
        print("Waiting for server offer...")

        while True:
            try:
                data, server = self.udp_socket.recvfrom(BUFFER_SIZE)

                # Validate message size
                if len(data) != 9:  # Expected size of offer message
                    continue

                # Unpack offer message
                magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!IbHH', data)

                # Validate message contents
                if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_OFFER:
                    continue

                print(f"Received offer from {server[0]}")
                return server[0], udp_port, tcp_port

            except Exception as e:
                print(f"Error receiving offer: {e}. Continuing to listen...")

    def tcp_transfer(self, server_ip: str, server_port: int, file_size: int,
                     connection_num: int) -> Optional[TransferStats]:
        """
        Perform TCP file transfer and measure performance.

        Args:
            server_ip: Server's IP address
            server_port: Server's TCP port
            file_size: Size of file to transfer in bytes
            connection_num: Connection identifier number

        Returns:
            TransferStats object or None if transfer failed
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)

        try:
            # Connect to server
            print(f"TCP #{connection_num}: Connecting to server...")
            sock.connect((server_ip, server_port))

            # Send file size request
            request = f"{file_size}\n"
            sock.send(request.encode())

            # Receive data and measure time
            start_time = time.time()
            bytes_received = 0

            while bytes_received < file_size:
                chunk = sock.recv(BUFFER_SIZE)
                if not chunk:
                    break
                bytes_received += len(chunk)

            # Calculate statistics
            total_time = time.time() - start_time
            speed = (bytes_received * 8) / total_time  # bits per second

            return TransferStats("TCP", connection_num, total_time, speed)

        except Exception as e:
            print(f"Error in TCP transfer #{connection_num}: {e}")
            return None

        finally:
            sock.close()

    def udp_transfer(self, server_ip: str, server_port: int, file_size: int,
                     connection_num: int) -> Optional[TransferStats]:
        """
        Perform UDP file transfer and measure performance.

        Args:
            server_ip: Server's IP address
            server_port: Server's UDP port
            file_size: Size of file to transfer in bytes
            connection_num: Connection identifier number

        Returns:
            TransferStats object or None if transfer failed
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(UDP_TIMEOUT)

        try:
            # Send request to server
            print(f"UDP #{connection_num}: Sending request...")
            request = struct.pack('!IbQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, file_size)
            sock.sendto(request, (server_ip, server_port))

            # Prepare for receiving data
            start_time = time.time()
            bytes_received = 0
            packets_received = 0
            total_packets = None
            last_packet_time = time.time()

            # Receive data until timeout
            while time.time() - last_packet_time < UDP_TIMEOUT:
                try:
                    data = sock.recv(BUFFER_SIZE)
                    last_packet_time = time.time()

                    # Validate packet size
                    if len(data) < 21:  # Minimum size with headers
                        continue

                    # Parse header
                    magic_cookie, msg_type, total_segments, segment_num = struct.unpack('!IbQQ', data[:21])

                    # Validate packet
                    if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_PAYLOAD:
                        continue

                    # Update total packets count
                    if total_packets is None:
                        total_packets = total_segments

                    # Process payload
                    payload = data[21:]
                    bytes_received += len(payload)
                    packets_received += 1

                except socket.timeout:
                    continue

            # Calculate statistics
            total_time = time.time() - start_time
            speed = (bytes_received * 8) / total_time  # bits per second
            packet_success = (packets_received / total_packets * 100) if total_packets else 0

            return TransferStats("UDP", connection_num, total_time, speed, packet_success)

        except Exception as e:
            print(f"Error in UDP transfer #{connection_num}: {e}")
            return None

        finally:
            sock.close()

    def print_transfer_stats(self, stats: TransferStats):
        """
        Print transfer statistics in a formatted way.

        Args:
            stats: TransferStats object containing transfer statistics
        """
        if stats.transfer_type == "TCP":
            print(f"TCP transfer #{stats.connection_num} finished, "
                  f"total time: {stats.total_time:.2f} seconds, "
                  f"total speed: {stats.speed:.1f} bits/second")
        else:
            print(f"UDP transfer #{stats.connection_num} finished, "
                  f"total time: {stats.total_time:.2f} seconds, "
                  f"total speed: {stats.speed:.1f} bits/second, "
                  f"percentage of packets received successfully: {stats.packets_received:.1f}%")

    def run(self):
        """Main client loop."""
        while True:
            try:
                # Get test parameters from user
                file_size, tcp_count, udp_count = self.get_user_parameters()

                # Wait for server offer
                server_ip, udp_port, tcp_port = self.receive_offer()

                # Start all transfers in parallel
                threads: List[threading.Thread] = []
                results: List[Optional[TransferStats]] = []

                print("Starting transfers...")

                # Launch TCP transfers
                for i in range(tcp_count):
                    thread = threading.Thread(
                        target=lambda: results.append(
                            self.tcp_transfer(server_ip, tcp_port, file_size, i + 1)
                        )
                    )
                    threads.append(thread)
                    thread.start()

                # Launch UDP transfers
                for i in range(udp_count):
                    thread = threading.Thread(
                        target=lambda: results.append(
                            self.udp_transfer(server_ip, udp_port, file_size, i + 1)
                        )
                    )
                    threads.append(thread)
                    thread.start()

                # Wait for all transfers to complete
                for thread in threads:
                    thread.join()

                # Print results
                print("\nTransfer Results:")
                for result in results:
                    if result:
                        self.print_transfer_stats(result)

                print("\nAll transfers complete, listening for offer requests...")

            except KeyboardInterrupt:
                print("\nClient shutting down...")
                sys.exit(0)

            except Exception as e:
                print(f"Error in client operation: {e}")
                print("Restarting client...")


if __name__ == "__main__":
    client = SpeedTestClient()
    client.run()