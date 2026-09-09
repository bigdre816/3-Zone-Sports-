# Three-Zone Sports + Moten IP Integration Deployment

## System Architecture

This repository contains TWO integrated systems:

### 1. Three-Zone Sports (Member Portal)
- **Location**: `/three-zone-mvp/` (backend) + `/docs/` (public website)
- **Purpose**: Live games, schedules, archives, member access
- **Tech**: Python 3.12, PostgreSQL in production, WebSocket
- **URL**: `https://3zonesports.com` (public) + `https://api.3zonesports.com`

### 2. Moten IP Control Plane (Audit & Evidence)
- **Location**: `/apps/control-plane/` (Phase 1) + `/index.html` (root prototype)
- **Purpose**: Invention tracking, disclosure control, rights/evidence preservation
- **Tech**: Python 3.12, SQLAlchemy, PostgreSQL/SQLite, append-only event chain
- **URL**: Dedicated Render service (for example `https://moten.3zonesports.com`)

## Integrated Deployment

Both systems share:
- The same GitHub repository
- Separate Render web services
- Separate PostgreSQL databases in production
- An authenticated, versioned evidence handoff: Three-Zone → Moten

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
   - Database: PostgreSQL + optional disk for demo media/cache

2. **Deploy Moten Control Plane to Separate Render Service**
   - Handles: Audit trail, disclosure firewall, evidence preservation
   - Database: PostgreSQL

3. **Connect Public Website (GitHub Pages)**
   - Already deployed: `https://3zonesports.com`
   - Needs: Backend URL in `docs/config.js`

### Integration

Events flow through verification:
```
Three-Zone Event → authenticated async handoff → Moten Audit Plane
```

Each game/archive is:
1. Created in Three-Zone
2. Handoff evidence is queued asynchronously for Moten
3. Moten preserves the immutable intake + audit chain
4. Optional anchoring remains simulation/testnet until production validation

## To Make Everything Active Right Now

I need to know:

1. **Do you want to deploy both systems to Render?**
   - Same service? (simpler)
   - Separate services? (better separation)

2. **Create separate PostgreSQL databases**
   - `three-zone-postgres`
   - `moten-postgres`

3. **Keep XRPL optional**
   - Simulation/testnet for new anchoring work
   - Never a runtime dependency for live games

Once you confirm these, I will:
- Set up both Render services
- Connect the evidence handoff endpoints
- Get the member and operator portals online
- Verify login, event lifecycle, rights revoke/restore, settlement, and Moten intake
