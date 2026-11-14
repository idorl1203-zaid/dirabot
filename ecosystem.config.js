module.exports = {
  apps: [{
    name: 'dirabot',
    script: '/opt/homebrew/bin/python3.11',
    args: '-m uvicorn server:app --host 0.0.0.0 --port 6008',
    cwd: '/Users/ze_ido/Desktop/DiraBot',
    interpreter: 'none',
    watch: false,
    autorestart: true,
    max_restarts: 10,
    restart_delay: 3000,
    env: {
      PYTHONPATH: '/Users/ze_ido/Desktop/DiraBot',
    },
    log_date_format: 'DD/MM HH:mm:ss',
    error_file: '/Users/ze_ido/Desktop/DiraBot/logs/error.log',
    out_file:   '/Users/ze_ido/Desktop/DiraBot/logs/out.log',
    merge_logs: true,
  }]
};
