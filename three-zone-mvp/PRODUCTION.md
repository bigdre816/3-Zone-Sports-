# Three-Zone Sports Backend Production Deployment Guide

## Quick Start

This guide prepares the Three-Zone Sports backend for production deployment on Render.com.

The full user-friendly deployment guide is in **DEPLOY-3ZONESPORTS.md** at the repository root. Read that first if you're new to this.

## Architecture

```
┌─────────────────────────────────────────┐
│  Public Website (GitHub Pages)          │
│  https://3zonesports.com                │
│  - Deployed from /docs                  │
│  - Static HTML/CSS/JS                   │
│  - Loads from config.js                 │
└──────────────────┬──────────────────────┘
                   │ API calls
                   ▼
┌─────────────────────────────────────────┐
│  Member Backend (Render)                │
│  https://[app].onrender.com             │
│  - Python 3.12                          │
│  - HTTP on :8000                        │
│  - WebSocket on :8765                   │
│  - SQLite on persistent disk            │
└─────────────────────────────────────────┘
```

## Files in This Directory

### Application
- `run.py` - Entry point. Starts HTTP and WebSocket servers.
- `requirements.txt` - Python dependencies (websockets only)
- `backend/` - Application code
  - `http_server.py` - HTTP request handler
  - `ws_server.py` - WebSocket server
  - `db.py` - SQLite database interface
  - `config.py` - Configuration management

### Configuration (Production)
- `.env.production` - Production environment variables template
- `render.yaml` - Render.com infrastructure-as-code (IaC)
- `runtime.txt` - Python version specification
- `.dockerignore` - Files excluded from deployment

### Supporting
- `README.md` - Application documentation
- `CONNECT-3ZONESPORTS.md` - Domain configuration guide

## Environment Variables Required

### Security (Set via Render Secrets)
- `TZ_TOKEN_SECRET` - JWT signing secret (32+ characters, random)
- `TZ_MEDIA_SERVICE_KEY` - Media service authentication (32+ characters, random)

### Server
- `TZ_ENV=production`
- `TZ_HTTP_HOST=0.0.0.0` (listen on all interfaces)
- `TZ_WS_HOST=0.0.0.0` (WebSocket listen all)
- `TZ_HTTP_PORT=8000`
- `TZ_WS_PORT=8765`

### Database
- `TZ_DATABASE_PATH=/var/data/three_zone.sqlite3` (persistent disk)

### Origins (CORS)
- `TZ_ALLOWED_ORIGINS=https://3zonesports.com,https://www.3zonesports.com`

### Media Providers
- `TZ_LIVE_MEDIA_PROVIDER=demo` (or `cloudflare`)
- `TZ_UGC_MEDIA_PROVIDER=fake` (or `cloudflare`)

## Render Deployment Steps

See **DEPLOY-3ZONESPORTS.md** for complete instructions.

Quick summary:
1. Generate two random secrets (40 chars each)
2. Connect Render to GitHub
3. Create Web Service from this repo
4. Set environment variables (including secrets)
5. Add persistent disk at `/var/data` (10GB)
6. Enable health check at `/api/health`
7. Deploy
8. Update `docs/config.js` with backend URL

## Production Checklist

- [ ] Render service deployed and running
- [ ] Backend URL added to `docs/config.js`
- [ ] GitHub Pages rebuilt (1-2 minutes after config.js change)
- [ ] Visit 3zonesports.com - Backend should show "Online"
- [ ] Test sign-in with `demo-viewer` / `change-me-viewer-local`
- [ ] Test member portal features (Live, Schedules, Archives)
- [ ] Check Render logs for errors
- [ ] Configure custom domain if needed

## Database

SQLite is persisted on Render's persistent disk at `/var/data/three_zone.sqlite3`.

**Important**: The persistent disk is deleted if you delete the web service. Back up data if needed.

To migrate to PostgreSQL later:
1. Set up Render PostgreSQL instance
2. Update connection string in `backend/config.py`
3. Run migration script
4. Update `TZ_DATABASE_PATH` environment variable
5. Redeploy

## Media Providers

### Demo Mode (Default)
- Generates fake video streams
- Works out of the box
- No credentials required
- Suitable for testing and demo

### Cloudflare Stream (Production)
- Real live video streaming
- Requires Cloudflare credentials
- Set environment variables:
  - `TZ_CLOUDFLARE_ACCOUNT_ID`
  - `TZ_CLOUDFLARE_API_TOKEN`
  - `TZ_CLOUDFLARE_CUSTOMER_CODE`
  - `TZ_CLOUDFLARE_WEBHOOK_SECRET`
- Set `TZ_LIVE_MEDIA_PROVIDER=cloudflare`
- Redeploy

## CORS and Security

The backend enforces strict CORS:
- Only allows requests from domains in `TZ_ALLOWED_ORIGINS`
- Development defaults to `http://127.0.0.1:8000` and `http://localhost:8000`
- Production refuses wildcard origins (`*`)

To add a new allowed origin:
1. Update `TZ_ALLOWED_ORIGINS` on Render
2. Redeploy

## WebSocket Configuration

The backend runs WebSocket server on a separate port (default 8765).

For production:
- WebSocket connects at `wss://[backend-domain]/ws/events/[event_id]`
- CORS is enforced on WebSocket upgrade
- Connection limits per IP: 20 concurrent

To modify WebSocket settings, update `backend/config.py`:
- `ws_max_message_bytes` - Max message size (default 16KB)
- `ws_max_messages_per_10s` - Rate limit (default 40)
- `ws_max_conns_per_ip` - Connection limit per IP (default 20)

## Health Check

Render uses `/api/health` to monitor the service.

- Returns `{"status": "ok"}` when healthy
- Response time should be <1 second
- If health check fails, Render will restart the service

To test locally:
```bash
curl http://localhost:8000/api/health
```

## Logs and Monitoring

View application logs on Render dashboard:
1. Go to your service
2. Click **Logs** tab
3. Logs update in real-time

Key log entries:
- Service startup
- HTTP requests
- WebSocket connections
- Database operations
- Errors and exceptions

## Scaling

The free tier on Render may be limited. If you need more resources:

1. Upgrade Render plan
2. Increase instance size (memory, CPU)
3. Enable auto-scaling if available
4. Consider CloudFlare CDN for static assets

## Troubleshooting

### Service won't start
- Check `TZ_TOKEN_SECRET` and `TZ_MEDIA_SERVICE_KEY` are set
- Check database path `/var/data` exists
- Check Python version (must be 3.12+)
- View Render logs for specific errors

### Backend Offline on public site
- Check Render service is running
- Check `TZ_ALLOWED_ORIGINS` includes public domain
- Check `docs/config.js` has correct backend URL
- Wait 1-2 minutes for GitHub Pages to rebuild

### Database errors
- Check persistent disk exists and has free space
- Check database path in environment variable
- Check file permissions (should be writable)

### High memory usage
- SQLite can use significant memory with large datasets
- Consider PostgreSQL migration
- Monitor query performance

## Future Improvements

- [ ] Migrate to PostgreSQL (easier scaling)
- [ ] Add Redis caching
- [ ] Enable Cloudflare Stream integration
- [ ] Configure XRPL blockchain audit
- [ ] Add structured logging (JSON format)
- [ ] Enable performance monitoring (Sentry, DataDog)
- [ ] Set up automated backups
- [ ] Add staging environment

## Support

- Backend code: See `README.md` in this directory
- Deployment help: See `DEPLOY-3ZONESPORTS.md`
- Render docs: https://render.com/docs
- Python docs: https://docs.python.org/3.12
