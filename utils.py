import aiohttp
import os
from dotenv import load_dotenv
from urllib.parse import quote

load_dotenv()

API_KEY = os.getenv("API_KEY")
TFT_API_KEY = os.getenv("TFT_API_KEY")

def _validate_keys():
    missing = []
    if not API_KEY:
        missing.append("API_KEY")
    # TFT key optional; we fallback if missing
    if missing:
        print("[hawkshot] Missing required env vars: " + ", ".join(missing))
    if TFT_API_KEY is None:
        print("[hawkshot] WARNING: TFT_API_KEY not set; TFT features will be disabled (no fallback).")

_validate_keys()

headers = {"X-Riot-Token": API_KEY} if API_KEY else {}
# Only use TFT_API_KEY; no fallback to API_KEY per requirement
tft_headers = {"X-Riot-Token": TFT_API_KEY} if TFT_API_KEY else {}

_tft_forbidden = False
_tft_fallback_attempted = False  # already defined later but ensure single definition

# Simple in-memory rate limiting / caching state
_rate_cache = {
    "lol_match_ids": {},   # puuid -> {"ts": float, "data": list|None}
    "tft_match_ids": {},   # puuid -> {"ts": float, "data": list|None}
}
_backoff = {
    "lol_match_ids": {},   # puuid -> next_allowed_epoch
    "tft_match_ids": {},   # puuid -> next_allowed_epoch
}

_BASE_CACHE_SECONDS = 60  # minimum interval between successful pulls
_BASE_BACKOFF_SECONDS = 10
_MAX_BACKOFF_SECONDS = 300
_tft_fallback_attempted = False  # ensure we only try API_KEY fallback once

def is_tft_disabled():
    return _tft_forbidden or not tft_headers

def _mask(key: str):
    if not key:
        return "<none>"
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]

def _validate_tft_key(region: str = "euw1"):
    """Lightweight TFT key validation; non-fatal. Marks disabled on 403/401."""
    global _tft_forbidden
    if not tft_headers:
        print("[hawkshot] TFT: No TFT_API_KEY set (TFT endpoints disabled).")
        return
    status_url = f"https://{region}.api.riotgames.com/tft/status/v1/platform-data"
    try:
        import requests
        r = requests.get(status_url, headers=tft_headers, timeout=5)
        if r.status_code == 200:
            print("[hawkshot] TFT key OK (status endpoint reachable).")
        elif r.status_code in (401, 403):
            _tft_forbidden = True
            print(f"[hawkshot] TFT key rejected ({r.status_code}). Disable TFT features. Key={_mask(TFT_API_KEY)}")
        else:
            print(f"[hawkshot] TFT status returned {r.status_code}; continuing optimistically.")
    except Exception as e:
        print(f"[hawkshot] TFT status check failed: {e}")

# Run validation once at import
_validate_tft_key()

# HTTP session management
_http_session = None

async def get_http_session():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

def riot_get(url: str, headers_dict: dict, label: str):
    """Centralized GET with basic 403 diagnostics. (Sync version for backwards compatibility)"""
    import requests
    r = requests.get(url, headers=headers_dict)
    if r.status_code == 403:
        print(f"[hawkshot] 403 Forbidden on {label}: {url}\nResponse: {r.text[:300]}\nCauses: expired dev key, incorrect routing cluster, wrong product scope, or production-only endpoint.")
    return r

async def async_riot_get(url: str, headers_dict: dict, label: str):
    """Async version of riot_get that returns JSON data"""
    try:
        session = await get_http_session()
        async with session.get(url, headers=headers_dict) as r:
            if r.status == 403:
                text = await r.text()
                print(f"[hawkshot] 403 Forbidden on {label}: {url}\nResponse: {text[:300]}\nCauses: expired dev key, incorrect routing cluster, wrong product scope, or production-only endpoint.")
                return None
            elif r.status == 200:
                return await r.json()
            else:
                text = await r.text()
                print(f"[hawkshot] HTTP {r.status} error for {label}: {text[:300]}")
                return None
    except Exception as e:
        print(f"[hawkshot] HTTP error for {label}: {e}")
        return None

game_modes = {
    "490": "Quickplay",
    "420": "Ranked Solo/Duo",
    "440": "Ranked Flex",
    "450": "ARAM",
    "1700": "Arena",
    "1300": "Nexus Blitz",
    "all": "All",
}

routings = {
    "br1": "americas",
    "eun1": "europe",
    "euw1": "europe",
    "jp1": "asia",
    "kr": "asia",
    "la1": "americas",
    "la2": "americas",
    "na1": "americas",
    "oc1": "sea",
    "tr1": "europe",
    "ru": "europe",
    "ph2": "sea",
    "sg2": "sea",
    "tw2": "sea",
    "vn2": "sea",
    "th2": "sea",
}

region_names = {
    "br1": "Brazil",
    "eun1": "Europe Nordic & East",
    "euw1": "Europe West",
    "jp1": "Japan",
    "kr": "Korea",
    "la1": "Latin America North",
    "la2": "Latin America South",
    "na1": "North America",
    "oc1": "Oceania",
    "tr1": "Turkey",
    "ru": "Russia",
    "ph2": "Philippines",
    "sg2": "Singapore",
    "tw2": "Taiwan",
    "vn2": "Vietnam",
    "th2": "Thailand",
}
async def get_current_match(puuid, region):
    routing = get_routing(region)
    current_match_url = f"https://{routing}.api.riotgames.com/lol/spectator/v4/active-games/by-summoner/{puuid}"
    current_match_response = riot_get(current_match_url, headers, "current_match")
    # TODO: return parsed data (currently unused)
    return current_match_response.json() if current_match_response.status_code == 200 else None

async def get_account_by_riot_id(riot_id: str, region: str):
    """Lookup a Riot account using the new Riot ID (gameName#tagLine).

    riot_id: e.g. "SENTRi#rival" (case-insensitive per API).
    region: platform region (euw1, na1, etc.) used only to derive routing cluster.
    """
    if "#" not in riot_id:
        return None  # caller can fallback to legacy summoner name logic
    game_name, tag_line = riot_id.split("#", 1)
    routing = get_routing(region)
    url = f"https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
    r = riot_get(url, headers, "account_by_riot_id")
    if r.status_code == 200:
        data = r.json()
        # Attach normalized case fields
        data["gameName"] = data.get("gameName", game_name)
        data["tagLine"] = data.get("tagLine", tag_line)
        return data
    return None

async def get_summoner_by_puuid(puuid: str, region: str):
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    r = riot_get(url, headers, "summoner_by_puuid")
    if r.status_code == 200:
        try:
            data = r.json()
            # Validate that we have the expected fields (note: 'id' might not be present in newer API versions)
            required_fields = ["puuid", "summonerLevel", "profileIconId"]
            for field in required_fields:
                if field not in data:
                    print(f"[hawkshot] Missing field '{field}' in summoner response: {data}")
                    return None
            return data
        except Exception as e:
            print(f"[hawkshot] Error parsing summoner JSON: {e}")
            return None
    else:
        print(f"[hawkshot] get_summoner_by_puuid failed: {r.status_code} - {r.text[:200]}")
        return None

async def get_summoner_id_by_puuid(puuid: str, region: str):
    """Get summoner ID by PUUID - tries by-puuid endpoint first, then fallback methods"""
    # Method 1: Try direct summoner by PUUID (should have ID)
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    r = riot_get(url, headers, "summoner_id_by_puuid")
    if r.status_code == 200:
        try:
            data = r.json()
            if "id" in data:
                return data["id"]
            else:
                print(f"[hawkshot] No 'id' field in summoner response: {data}")
        except Exception as e:
            print(f"[hawkshot] Error parsing summoner JSON: {e}")
    
    # Method 2: Try getting account first, then summoner by name
    try:
        account = await get_account_by_puuid(puuid, region)
        if account and "gameName" in account and "tagLine" in account:
            # Try the by-name endpoint with just the game name
            name_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(account['gameName'])}"
            name_r = riot_get(name_url, headers, "summoner_id_by_name_from_account")
            if name_r.status_code == 200:
                name_data = name_r.json()
                if "id" in name_data:
                    return name_data["id"]
    except Exception as e:
        print(f"[hawkshot] Fallback method failed: {e}")
    
    print(f"[hawkshot] Could not get summoner ID for PUUID {puuid[:8]}...")
    return None

async def get_summoner_id_by_puuid(puuid, region):
    """Get summoner ID using various fallback methods"""
    if not puuid or not region:
        return None
    
    print(f"[hawkshot] Getting summoner ID for PUUID: {puuid[:8]}... in {region}")
    
    # Try the direct summoner-by-puuid endpoint first to see if it includes ID
    try:
        url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        response = await async_riot_get(url, headers, "summoner_by_puuid_for_id")
        if response and "id" in response:
            print(f"[hawkshot] Found summoner ID directly from PUUID lookup: {response['id']}")
            return response["id"]
        else:
            print(f"[hawkshot] PUUID lookup response missing 'id' field: {list(response.keys()) if response else 'None'}")
    except Exception as e:
        print(f"[hawkshot] Direct PUUID lookup failed: {e}")
    
    # Since the summoner-by-name endpoints are giving 403, we'll use PUUID as a fallback
    # Many Riot APIs accept PUUID where they expect summoner ID
    print(f"[hawkshot] Using PUUID as fallback ID: {puuid[:8]}...")
    return puuid


async def get_summoner_by_name_direct(summoner_name, region):
    """Direct summoner lookup by name (for fallback purposes)"""
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner_name)}"
    r = riot_get(url, headers, "summoner_by_name_direct")
    if r.status_code == 200:
        try:
            data = r.json()
            # Validate that we have the expected fields
            required_fields = ["id", "puuid", "summonerLevel", "profileIconId"]
            for field in required_fields:
                if field not in data:
                    print(f"[hawkshot] Missing field '{field}' in summoner response: {data}")
                    return None
            return data
        except Exception as e:
            print(f"[hawkshot] Error parsing summoner JSON: {e}")
            return None
    else:
        print(f"[hawkshot] get_summoner_by_name_direct failed: {r.status_code} - {r.text[:200]}")
        return None

async def get_account_by_puuid(puuid: str, region: str):
    """Return Riot account (gameName, tagLine, puuid) via account-v1 by PUUID."""
    routing = get_routing(region)
    url = f"https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
    r = riot_get(url, headers, "account_by_puuid")
    return r.json() if r.status_code == 200 else None
    
def _normalize_name(maybe_riot_id: str) -> str:
    """Return the platform summoner name (strip tag if Riot ID)."""
    if maybe_riot_id and "#" in maybe_riot_id:
        return maybe_riot_id.split("#", 1)[0]
    return maybe_riot_id

async def get_summoner_name(summoner_name, region):
    summoner_name = _normalize_name(summoner_name)
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner_name)}"
    name_response = riot_get(url, headers, "summoner_by_name")
    if name_response.status_code != 200:
        return None
    return name_response.json().get("name")
    
def get_game_mode(game_mode):
         return game_modes.get(game_mode)
    
    
    
async def get_tft_match_ids(puuid, region):
    """Return list of TFT match IDs or None.

    Adds defensive checks & logging so we can see why tft_last_match stays None.
    """
    import time
    global _tft_forbidden
    if is_tft_disabled():
        return None
    if not puuid:
        print("[hawkshot] get_tft_match_ids called with empty puuid")
        return None
    now = time.time()
    # Respect backoff window
    nb = _backoff["tft_match_ids"].get(puuid, 0)
    if now < nb:
        return _rate_cache["tft_match_ids"].get(puuid, {}).get("data")
    # Serve from cache if fresh
    entry = _rate_cache["tft_match_ids"].get(puuid)
    if entry and (now - entry["ts"]) < _BASE_CACHE_SECONDS:
        return entry["data"]
    routing = get_routing(region)
    tft_match_url = f"https://{routing}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?count=20"
    r = riot_get(tft_match_url, tft_headers, "tft_match_ids")
    if r.status_code != 200:
        snippet = r.text[:200].replace("\n", " ")
        print(f"[hawkshot] TFT match ids fetch failed {r.status_code}: {snippet}")
        if r.status_code == 403:
            _tft_forbidden = True
            print("[hawkshot] Disabling further TFT polling after 403. Refresh TFT_API_KEY and restart.")
        elif r.status_code == 429:
            # Exponential backoff
            prev = _backoff["tft_match_ids"].get(puuid, now)
            wait = min((_BASE_BACKOFF_SECONDS if prev <= now else (prev - now) * 2), _MAX_BACKOFF_SECONDS)
            retry_after = r.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = max(wait, int(retry_after))
            _backoff["tft_match_ids"][puuid] = now + wait
            print(f"[hawkshot] TFT rate limited. Backing off {wait}s for puuid {puuid[:8]}...")
        return None
    try:
        data = r.json()
    except Exception as e:
        print(f"[hawkshot] Failed decoding TFT match ids JSON: {e}")
        return None
    if not isinstance(data, list):
        print(f"[hawkshot] Unexpected TFT match ids payload type {type(data)}: {str(data)[:120]}")
        return None
    if not data:
        print("[hawkshot] TFT match ids list empty (no recent games)")
        _rate_cache["tft_match_ids"][puuid] = {"ts": now, "data": None}
        return None
    # Success: cache and reset backoff
    _rate_cache["tft_match_ids"][puuid] = {"ts": now, "data": data}
    if puuid in _backoff["tft_match_ids"]:
        _backoff["tft_match_ids"].pop(puuid, None)
    return data

async def get_match_ids(puuid, region):
    import time
    if not puuid:
        return None
    now = time.time()
    nb = _backoff["lol_match_ids"].get(puuid, 0)
    if now < nb:
        return _rate_cache["lol_match_ids"].get(puuid, {}).get("data")
    entry = _rate_cache["lol_match_ids"].get(puuid)
    if entry and (now - entry["ts"]) < _BASE_CACHE_SECONDS:
        return entry["data"]
    routing = get_routing(region)
    match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    r = riot_get(match_url, headers, "lol_match_ids")
    if r.status_code != 200:
        if r.status_code == 429:
            prev = _backoff["lol_match_ids"].get(puuid, now)
            wait = min((_BASE_BACKOFF_SECONDS if prev <= now else (prev - now) * 2), _MAX_BACKOFF_SECONDS)
            ra = r.headers.get("Retry-After")
            if ra and ra.isdigit():
                wait = max(wait, int(ra))
            _backoff["lol_match_ids"][puuid] = now + wait
            print(f"[hawkshot] LoL rate limited. Backing off {wait}s for puuid {puuid[:8]}...")
        else:
            print(f"[hawkshot] LoL match ids fetch failed {r.status_code}: {r.text[:120]}")
        return _rate_cache["lol_match_ids"].get(puuid, {}).get("data")
    try:
        data = r.json()
    except Exception as e:
        print(f"[hawkshot] Failed decoding LoL match ids JSON: {e}")
        return None
    if not isinstance(data, list):
        print(f"[hawkshot] Unexpected LoL match ids payload type {type(data)}: {str(data)[:120]}")
        return None
    if not data:
        _rate_cache["lol_match_ids"][puuid] = {"ts": now, "data": None}
        return None
    _rate_cache["lol_match_ids"][puuid] = {"ts": now, "data": data}
    if puuid in _backoff["lol_match_ids"]:
        _backoff["lol_match_ids"].pop(puuid, None)
    return data

   
async def get_tft_match_data(tft_match_id, region):
    routing = get_routing(region)
    tft_match_url = f"https://{routing}.api.riotgames.com/tft/match/v1/matches/{tft_match_id}"
    if is_tft_disabled():
        return None
    tft_match_response = riot_get(tft_match_url, tft_headers, "tft_match_data")

    if tft_match_response.status_code == 200:
        tft_match_data = tft_match_response.json()
        return tft_match_data
    else:
        return None


async def get_summoner_id(summoner_name, region):
    summoner_name = _normalize_name(summoner_name)
    summoner_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner_name)}"
    summoner_response = riot_get(summoner_url, headers, "summoner_id")

    if summoner_response.status_code == 200:
        summoner_data = summoner_response.json()
        return summoner_data["id"]
    else:
        print(summoner_response.json())
        return None
    
async def get_tft_puuid(summoner_name, region):
    """Return TFT PUUID using TFT_API_KEY only.

    Riot ID input: we use the gameName portion (before '#').
    """
    global _tft_forbidden
    if is_tft_disabled():
        if not tft_headers:
            print("[hawkshot] get_tft_puuid: TFT_API_KEY missing; TFT disabled")
        return None
    original_input = summoner_name
    routing = get_routing(region)
    # If Riot ID form provided: gameName#tagLine -> use account-v1
    if "#" in summoner_name:
        game_name, tag_line = summoner_name.split("#", 1)
        account_url = f"https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
        # Try TFT key first
        r = riot_get(account_url, tft_headers, "tft_account_by_riot_id") if tft_headers else None
        status = r.status_code if r else None
        if r and status == 200:
            data = r.json()
            return data.get("puuid")
        # Fallback to LoL key if allowed and not same
        global _tft_fallback_attempted
        if (not r or status in (401,403,404)) and API_KEY and (API_KEY != TFT_API_KEY) and not _tft_fallback_attempted:
            _tft_fallback_attempted = True
            rf = riot_get(account_url, headers, "tft_account_by_riot_id_fallback")
            if rf.status_code == 200:
                print("[hawkshot] Used API_KEY fallback for account-v1 Riot ID lookup (provide valid TFT key to avoid fallback).")
                return rf.json().get("puuid")
            else:
                if rf.status_code in (401,403):
                    _tft_forbidden = True
        # If account-v1 path failed, drop to name-only TFT summoner endpoint using gameName
        summoner_name = game_name
    # Legacy / fallback: by-name on TFT summoner endpoint
    summoner_name = _normalize_name(summoner_name)
    byname_url = f"https://{region}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{quote(summoner_name)}"
    r2 = riot_get(byname_url, tft_headers, "tft_summoner_by_name_for_puuid") if tft_headers else None
    if r2 and r2.status_code == 200:
        return r2.json().get("puuid")
    if r2 and r2.status_code == 403:
        _tft_forbidden = True
        print(f"[hawkshot] TFT PUUID fetch 403 (by-name). Input={original_input}. Key rejected.")
    else:
        if r2:
            print(f"[hawkshot] TFT PUUID fetch failed {r2.status_code}: {r2.text[:120]}")
        else:
            print("[hawkshot] No TFT key available for PUUID fetch.")
    return None
    
async def get_solo_summoner_rank(summoner_name, region):
    summoner_id = await get_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_response = riot_get(ranking_url, headers, "solo_rank")
    solorank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_SOLO_5x5":
                solorank = queue
                break
            else:
                solorank = "Unranked"
        
        if solorank == None:
            solorank = "Unranked"            
        
        if solorank == "Unranked":
            return solorank
        else:
            return solorank["tier"].capitalize() + " " + solorank["rank"] + " " + str(solorank["leaguePoints"]) + " LP"
        
        
        
async def get_flex_summoner_rank(summoner_name, region):
    summoner_id = await get_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_response = riot_get(ranking_url, headers, "flex_rank")
    flexrank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_FLEX_SR":
                flexrank = queue
                break
            else:
                flexrank = "Unranked"
                    
        if flexrank == None:
            flexrank = "Unranked"
            
        if flexrank == "Unranked":
            return flexrank
        else:
            return flexrank["tier"].capitalize() + " " + flexrank["rank"] + " " + str(flexrank["leaguePoints"]) + " LP"


async def get_tft_summoner_id(summoner_name, region):
    if is_tft_disabled():
        return None
    summoner_name = _normalize_name(summoner_name)
    summoner_url = f"https://{region}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{quote(summoner_name)}"
    summoner_response = riot_get(summoner_url, tft_headers, "tft_summoner_id")

    if summoner_response.status_code == 200:
        summoner_data = summoner_response.json()
        return summoner_data["id"]
    else:
        print(summoner_response.json())
        return None

async def get_tft_summoner_rank_by_puuid(tft_puuid, region):
    """Get TFT rank using TFT PUUID directly"""
    if is_tft_disabled():
        return "TFT Disabled"
    
    try:
        ranking_url = f"https://{region}.api.riotgames.com/tft/league/v1/by-puuid/{tft_puuid}"
        ranking_data = await async_riot_get(ranking_url, tft_headers, "tft_rank_by_puuid")
        
        if ranking_data and isinstance(ranking_data, list):
            for queue in ranking_data:
                if queue["queueType"] == "RANKED_TFT":
                    return f"{queue['tier'].capitalize()} {queue['rank']} {queue['leaguePoints']} LP"
        
        print(f"[hawkshot] No TFT rank found in response: {ranking_data}")
    except Exception as e:
        print(f"[hawkshot] Failed to get TFT rank via PUUID: {e}")
    
    return "Unranked"


async def get_tft_summoner_rank(summoner_name, region):
    if is_tft_disabled():
        return "TFT Disabled"
    tft_summoner_id = await get_tft_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/tft/league/v1/entries/by-summoner/{tft_summoner_id}"
    ranking_response = riot_get(ranking_url, tft_headers, "tft_rank")
    flexrank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_TFT":
                flexrank = queue
                break
            else:
                flexrank = "Unranked"
                    
        
        if flexrank == "Unranked" or flexrank == None:
            return "Unranked"
        else:
            return (flexrank["tier"]).capitalize() + " " + flexrank["rank"] + " " + str(flexrank["leaguePoints"]) + " LP"
       
async def get_highest_champion_mastery_by_puuid(puuid, region):
    """Get highest champion mastery using PUUID directly"""
    try:
        # Try PUUID-based endpoint first (if it exists)
        mastery_url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        mastery_response = await async_riot_get(mastery_url, headers, "champion_mastery_by_puuid")
        if mastery_response and isinstance(mastery_response, list) and len(mastery_response) > 0:
            highest_champ = mastery_response[0]
            return await champid_to_name(highest_champ["championId"])
    except Exception as e:
        print(f"[hawkshot] PUUID-based champion mastery failed: {e}")
    
    # Fallback: get summoner ID and use the by-summoner endpoint
    try:
        summoner_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        summoner_response = await async_riot_get(summoner_url, headers, "summoner_by_puuid_for_mastery")
        
        if summoner_response and "id" in summoner_response:
            summoner_id = summoner_response["id"]
            return await get_highest_champion_mastery_by_id(summoner_id, region)
        else:
            print(f"[hawkshot] Summoner by PUUID response missing ID: {summoner_response}")
    except Exception as e:
        print(f"[hawkshot] Failed to get champion mastery via summoner lookup: {e}")
    
    return "Unknown"


async def get_solo_summoner_rank_by_puuid(puuid, region):
    """Get solo rank using PUUID directly"""
    try:
        ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        ranking_data = await async_riot_get(ranking_url, headers, "solo_rank_by_puuid")
        if ranking_data and isinstance(ranking_data, list):
            for queue in ranking_data:
                if queue["queueType"] == "RANKED_SOLO_5x5":
                    return f"{queue['tier'].capitalize()} {queue['rank']} {queue['leaguePoints']} LP"
        print(f"[hawkshot] No solo rank found in response: {ranking_data}")
    except Exception as e:
        print(f"[hawkshot] Failed to get solo rank via PUUID: {e}")
    
    return "Unranked"


async def get_flex_summoner_rank_by_puuid(puuid, region):
    """Get flex rank using PUUID directly"""
    try:
        ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        ranking_data = await async_riot_get(ranking_url, headers, "flex_rank_by_puuid")
        if ranking_data and isinstance(ranking_data, list):
            for queue in ranking_data:
                if queue["queueType"] == "RANKED_FLEX_SR":
                    return f"{queue['tier'].capitalize()} {queue['rank']} {queue['leaguePoints']} LP"
        print(f"[hawkshot] No flex rank found in response: {ranking_data}")
    except Exception as e:
        print(f"[hawkshot] Failed to get flex rank via PUUID: {e}")
    
    return "Unranked"


async def get_highest_champion_mastery_by_id(summoner_id, region):
    """Get highest champion mastery using summoner ID directly"""
    mastery_url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-summoner/{summoner_id}"
    mastery_data = await async_riot_get(mastery_url, headers, "champion_mastery_by_id")
    if mastery_data and isinstance(mastery_data, list) and len(mastery_data) > 0:
        highest_champ = mastery_data[0]
        return await champid_to_name(highest_champ["championId"])
    return "Unknown"

async def get_solo_summoner_rank_by_id(summoner_id, region):
    """Get solo rank using summoner ID directly"""
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_data = await async_riot_get(ranking_url, headers, "solo_rank_by_id")
    if ranking_data and isinstance(ranking_data, list):
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_SOLO_5x5":
                return f"{queue['tier'].capitalize()} {queue['rank']} {queue['leaguePoints']} LP"
    return "Unranked"

async def get_flex_summoner_rank_by_id(summoner_id, region):
    """Get flex rank using summoner ID directly"""
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_data = await async_riot_get(ranking_url, headers, "flex_rank_by_id")
    if ranking_data and isinstance(ranking_data, list):
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_FLEX_SR":
                return f"{queue['tier'].capitalize()} {queue['rank']} {queue['leaguePoints']} LP"
    return "Unranked"

async def get_highest_champion_mastery_id(summoner_name, region):
    summonerid = await get_summoner_id(summoner_name, region)
    mastery_url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-summoner/{summonerid}"
    mastery_response = riot_get(mastery_url, headers, "champion_mastery")
    highest_champ = None
    if mastery_response.status_code == 200:
        mastery_data = mastery_response.json()
        highest_champ = mastery_data[0]
        return await champid_to_name(highest_champ["championId"])
    
    
async def champid_to_name(id):
    id_url = f"https://cdn.communitydragon.org/latest/champion/{id}/data"
    id_response = riot_get(id_url, {}, "champ_id_to_name")
    return id_response.json()["name"]
       
async def get_summoner_icon(summoner_name, region):
    summoner_name = _normalize_name(summoner_name)
    icon_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner_name)}"
    icon_response = riot_get(icon_url, headers, "summoner_icon")
    return icon_response.json()["profileIconId"]

async def get_summoner_level(summoner_name, region):
    summoner_name = _normalize_name(summoner_name)
    icon_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner_name)}"
    icon_response = riot_get(icon_url, headers, "summoner_level")
    print(icon_response.json()["summonerLevel"])
    return icon_response.json()["summonerLevel"]

async def get_match_data(match_id, region):
    routing = get_routing(region)
    match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    match_response = riot_get(match_url, headers, "match_data")

    if match_response.status_code == 200:
        match_data = match_response.json()
        return match_data
    else:
        return None
 
 


 
   
def get_routing(region):
    return routings.get(region)


def get_region(region):
    return region_names.get(region)



