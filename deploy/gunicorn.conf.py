"""One web process keeps request slots and Yahoo's session lock shared."""
bind = '127.0.0.1:8020'
workers = 1
worker_class = 'gthread'
threads = 8  # Five numerical slots, with room for progress/navigation requests.
timeout = 120  # Worker heartbeat timeout, NOT a hard request deadline with gthread.
graceful_timeout = 120
forwarded_allow_ips = '127.0.0.1,::1'
accesslog = None
errorlog = '-'
control_socket_disable = True
