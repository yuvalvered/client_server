import socket
import struct
import threading
import time
import sys
from typing import Tuple, List, Optional
from dataclasses import dataclass
from colorama import init, Fore, Style

# Initialize colorama
init(autoreset=True)


# Color formatting functions
def success(msg): return f"{Fore.GREEN}{msg}{Style.RESET_ALL}"


def error(msg): return f"{Fore.RED}{msg}{Style.RESET_ALL}"


def info(msg): return f"{Fore.CYAN}{msg}{Style.RESET_ALL}"


def warning(msg): return f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"


def highlight(msg): return f"{Fore.MAGENTA}{msg}{Style.RESET_ALL}"


# Network protocol constants
MAGIC_COOKIE = 0xabcddcba
MSG_TYPE_OFFER = 0x2
MSG_TYPE_REQUEST = 0x3
MSG_TYPE_PAYLOAD = 0x4
BROADCAST_PORT = 13117
BUFFER_SIZE = 1024

# Increased timeout settings
UDP_TIMEOUT = 2.0
TCP_TIMEOUT = 10.0

# Increase system-wide socket timeout
socket.setdefaulttimeout(60)


@dataclass
class TransferStats:
    """Statistics for a file transfer."""
    transfer_type: str
    connection_num: int
    total_time: float
    speed: float
    packets_received: Optional[float] = None
    error_message: Optional[str] = None


class SpeedTestClient:
    def __init__(self):
        """Initialize the speed test client with enhanced socket options."""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.bind(('', BROADCAST_PORT))
            print(info("Client started, listening for offer requests..."))
        except Exception as e:
            print(error(f"Failed to initialize client: {e}"))
            sys.exit(1)

    def get_user_parameters(self) -> Tuple[int, int, int]:
        """Get test parameters from user input with validation."""
        while True:
            try:
                print(info("Please enter test parameters:"))
                file_size = int(input(info("File size (in bytes): ")))
                tcp_connections = int(input(info("Number of TCP connections: ")))
                udp_connections = int(input(info("Number of UDP connections: ")))

                if file_size <= 0:
                    raise ValueError("File size must be positive")
                if tcp_connections < 0 or udp_connections < 0:
                    raise ValueError("Number of connections cannot be negative")
                if tcp_connections == 0 and udp_connections == 0:
                    raise ValueError("Must have at least one connection")

                # Add warning for large number of connections
                if tcp_connections + udp_connections > 150:
                    print(warning("Warning: Large number of connections may impact performance"))

                return file_size, tcp_connections, udp_connections

            except ValueError as e:
                print(error(f"Invalid input: {str(e)}. Please try again."))

    def receive_offer(self) -> Tuple[str, int, int]:
        """Wait for and process server offer messages with timeout."""
        print(info("Waiting for server offer..."))

        while True:
            try:
                data, server = self.udp_socket.recvfrom(BUFFER_SIZE)
                if len(data) != 9:
                    continue

                magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!IbHH', data)

                if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_OFFER:
                    continue

                print(success(f"Received offer from {highlight(server[0])}"))
                return server[0], udp_port, tcp_port

            except Exception as e:
                print(error(f"Error receiving offer: {e}. Continuing to listen..."))

    def tcp_transfer(self, server_ip: str, server_port: int, file_size: int,
                     connection_num: int) -> TransferStats:
        """Perform TCP file transfer with retry logic."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)

        try:
            # Connection retry logic
            max_retries = 3
            retry_count = 0
            connection_success = False

            while retry_count < max_retries and not connection_success:
                try:
                    print(info(f"TCP #{connection_num}: Connecting to server (attempt {retry_count + 1})..."))
                    sock.connect((server_ip, server_port))
                    connection_success = True
                except (socket.timeout, ConnectionRefusedError) as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        return TransferStats("TCP", connection_num, 0, 0, error_message=str(e))
                    time.sleep(0.5)  # Wait before retry

            # Set socket options for better performance
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            request = f"{file_size}\n"
            sock.send(request.encode())

            start_time = time.time()
            bytes_received = 0
            chunk_size = min(BUFFER_SIZE * 4, file_size)  # Increased chunk size

            while bytes_received < file_size:
                try:
                    chunk = sock.recv(chunk_size)
                    if not chunk:
                        break
                    bytes_received += len(chunk)
                except socket.timeout:
                    break

            total_time = time.time() - start_time
            speed = (bytes_received * 8) / total_time if total_time > 0 else 0

            if bytes_received < file_size:
                return TransferStats("TCP", connection_num, total_time, speed,
                                     error_message="Incomplete transfer")

            return TransferStats("TCP", connection_num, total_time, speed)

        except Exception as e:
            print(error(f"Error in TCP transfer #{connection_num}: {e}"))
            return TransferStats("TCP", connection_num, 0, 0, error_message=str(e))

        finally:
            sock.close()

    def udp_transfer(self, server_ip: str, server_port: int, file_size: int,
                     connection_num: int) -> TransferStats:
        """Perform UDP file transfer with improved reliability."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(UDP_TIMEOUT)

        try:
            print(info(f"UDP #{connection_num}: Sending request..."))
            request = struct.pack('!IbQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, file_size)

            # Add retry logic for UDP request
            max_retries = 3
            for retry in range(max_retries):
                sock.sendto(request, (server_ip, server_port))

                start_time = time.time()
                bytes_received = 0
                packets_received = 0
                total_packets = None
                last_packet_time = time.time()

                while time.time() - last_packet_time < UDP_TIMEOUT:
                    try:
                        data = sock.recv(BUFFER_SIZE)
                        last_packet_time = time.time()

                        if len(data) < 21:
                            continue

                        magic_cookie, msg_type, total_segments, segment_num = struct.unpack('!IbQQ', data[:21])

                        if magic_cookie != MAGIC_COOKIE or msg_type != MSG_TYPE_PAYLOAD:
                            continue

                        if total_packets is None:
                            total_packets = total_segments

                        payload = data[21:]
                        bytes_received += len(payload)
                        packets_received += 1

                    except socket.timeout:
                        continue

                if bytes_received > 0:  # If we received any data, break the retry loop
                    break

                if retry < max_retries - 1:
                    time.sleep(0.5)  # Wait before retry

            total_time = time.time() - start_time
            speed = (bytes_received * 8) / total_time if total_time > 0 else 0
            packet_success = (packets_received / total_packets * 100) if total_packets else 0

            return TransferStats("UDP", connection_num, total_time, speed, packet_success)

        except Exception as e:
            print(error(f"Error in UDP transfer #{connection_num}: {e}"))
            return TransferStats("UDP", connection_num, 0, 0, 0, str(e))

        finally:
            sock.close()

    def print_transfer_stats(self, stats: TransferStats):
        """Print transfer statistics with error handling."""
        if stats.error_message:
            print(error(
                f"{stats.transfer_type} transfer #{stats.connection_num} failed: {stats.error_message}"
            ))
            return

        if stats.transfer_type == "TCP":
            print(success(
                f"TCP transfer #{stats.connection_num} finished, "
                f"total time: {stats.total_time:.2f} seconds, "
                f"total speed: {highlight(f'{stats.speed:.1f} bits/second')}"
            ))
        else:
            print(success(
                f"UDP transfer #{stats.connection_num} finished, "
                f"total time: {stats.total_time:.2f} seconds, "
                f"total speed: {highlight(f'{stats.speed:.1f} bits/second')}, "
                f"packets received: {warning(f'{stats.packets_received:.1f}%')}"
            ))

    def run(self):
        """Main client loop with improved connection handling."""
        while True:
            try:
                file_size, tcp_count, udp_count = self.get_user_parameters()
                server_ip, udp_port, tcp_port = self.receive_offer()

                threads: List[threading.Thread] = []
                results: List[TransferStats] = []

                def start_transfer(transfer_func, port, i):
                    time.sleep(0.1 * i)  # Stagger connection starts
                    results.append(transfer_func(server_ip, port, file_size, i + 1))

                print(info("Starting transfers..."))

                # Start TCP transfers with delay
                for i in range(tcp_count):
                    thread = threading.Thread(
                        target=lambda i=i: start_transfer(self.tcp_transfer, tcp_port, i)
                    )
                    threads.append(thread)
                    thread.start()

                # Start UDP transfers with delay
                for i in range(udp_count):
                    thread = threading.Thread(
                        target=lambda i=i: start_transfer(self.udp_transfer, udp_port, i)
                    )
                    threads.append(thread)
                    thread.start()

                # Wait for all transfers to complete
                for thread in threads:
                    thread.join()

                # Print detailed results
                print(highlight("\nTransfer Results:"))
                tcp_success = sum(1 for r in results if r.transfer_type == "TCP" and not r.error_message)
                udp_success = sum(1 for r in results if r.transfer_type == "UDP" and not r.error_message)

                print(info(f"\nSuccess Rate:"))
                print(success(f"TCP: {tcp_success}/{tcp_count} successful transfers"))
                print(success(f"UDP: {udp_success}/{udp_count} successful transfers"))

                for result in results:
                    self.print_transfer_stats(result)

                print(info("\nAll transfers complete, listening for offer requests..."))

            except KeyboardInterrupt:
                print(warning("\nClient shutting down..."))
                sys.exit(0)

            except Exception as e:
                print(error(f"Error in client operation: {e}"))
                print(warning("Restarting client..."))


if __name__ == "__main__":
    client = SpeedTestClient()
    client.run()