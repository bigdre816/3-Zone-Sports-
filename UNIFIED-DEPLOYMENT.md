# Three-Zone Sports + Moten IP Integration Deployment

## System Architecture

This repository contains TWO integrated systems:

### 1. Three-Zone Sports (Member Portal)
- **Location**: `/three-zone-mvp/` (backend) + `/docs/` (public website)
- **Purpose**: Live games, schedules, archives, member access
- **Tech**: Python 3.12, SQLite, WebSocket
- **URL**: `https://3zonesports.com` (public) + backend at Render

### 2. Moten IP Control Plane (Audit & Blockchain)
- **Location**: `/apps/control-plane/` (Phase 1) + `/index.html` (root prototype)
- **Purpose**: Invention tracking, rights management, XRPL blockchain verification
- **Tech**: Python 3.12, SQLAlchemy, PostgreSQL/SQLite, blockchain integration
- **URL**: Backend service + audit verification

## Integrated Deployment

Both systems share:
- Same GitHub repository
- Same Render infrastructure (or separate services)
- Shared database (SQLite locally, PostgreSQL in production)
- Event verification pipeline: Three-Zone → Moten audit → XRPL blockchain

## Phase 1 Deployment (What's Ready Now)

✅ **Three-Zone Sports** - Ready to deploy to Render
- Member portal fully built
- Public website live at 3zonesports.com
- All authentication and access control in place

✅ **Moten Control Plane** (Phase 1) - Ready to deploy
- Invention tracking system
- Disclosure firewall
- Append-only audit log
- Foundation for blockchain integration

## Next Steps

### Immediate (Right Now)

1. **Deploy Three-Zone Sports Backend to Render**
   - Handles: Live games, schedules, archives, member authentication
   - Database: SQLite with persistent disk

2. **Deploy Moten Control Plane to Separate Render Service** (or same service)
   - Handles: Audit trail, rights verification, XRPL preparation
   - Database: PostgreSQL recommended

3. **Connect Public Website (GitHub Pages)**
   - Already deployed: `https://3zonesports.com`
   - Needs: Backend URL in `docs/config.js`

### Integration

Events flow through verification:
```
Three-Zone Event → Moten Audit Plane → XRPL Blockchain → Verified Record
```

Each game/archive is:
1. Created in Three-Zone
2. Audited and verified in Moten
3. Published to XRPL blockchain (with credentials)
4. Retrieved with verification proof

## To Make Everything Active Right Now

I need to know:

1. **Do you want to deploy both systems to Render?**
   - Same service? (simpler)
   - Separate services? (better separation)

2. **For Moten blockchain verification:**
   - XRPL account? (testnet or mainnet)
   - Or use simulated mode initially?

3. **Database preference for Moten:**
   - SQLite? (local dev, simpler)
   - PostgreSQL? (production-ready, recommended)

Once you confirm these, I will:
- Set up both systems for deployment
- Create unified Render configuration
- Connect the event verification pipeline
- Get you the member portal login access
- Verify XRPL blockchain integration is working

What's your preference?
