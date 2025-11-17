import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResolveRequest(BaseModel):
    url: HttpUrl


class ResolveResponse(BaseModel):
    source_url: str
    download_url: Optional[str] = None
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    site_name: Optional[str] = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_from_meta(html: str, prop: str) -> Optional[str]:
    # Simple extraction for <meta property="og:video" content="...">
    import re

    # Try property
    m = re.search(
        rf'<meta[^>]+property=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)

    # Try name
    m = re.search(
        rf'<meta[^>]+name=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)

    return None


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        # Try to import database module
        from database import db

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"

            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    # Check environment variables
    import os as _os

    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


@app.post("/api/resolve", response_model=ResolveResponse)
def resolve_media(payload: ResolveRequest):
    """
    Resolve a public Instagram reel/post URL to a direct media URL using open graph tags.
    Note: Works only for publicly accessible URLs. Private or age-restricted media won't resolve.
    """
    url = str(payload.url)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}")

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail="Source page returned an error")

    html = resp.text

    # Extract from common meta tags
    video_url = (
        extract_from_meta(html, "og:video")
        or extract_from_meta(html, "twitter:player:stream")
        or extract_from_meta(html, "og:video:url")
        or extract_from_meta(html, "og:video:secure_url")
    )
    title = extract_from_meta(html, "og:title") or extract_from_meta(html, "twitter:title")
    thumb = extract_from_meta(html, "og:image") or extract_from_meta(html, "twitter:image")
    site_name = extract_from_meta(html, "og:site_name")

    data = {
        "source_url": url,
        "download_url": video_url,
        "title": title,
        "thumbnail": thumb,
        "site_name": site_name,
    }

    if not video_url:
        # Instagram often blocks scraping without auth. Provide a friendly message.
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not resolve a direct video URL. The link may be private or requires authentication. "
                "Try a public reel/post URL."
            ),
        )

    return data


@app.get("/api/proxy")
async def proxy(u: str = Query(..., description="Direct media URL to fetch and stream")):
    """
    Lightweight proxy to fetch a media file with a browser-friendly content type.
    Use only for small files; this does not implement full range requests.
    """
    try:
        r = requests.get(u, headers=HEADERS, timeout=20, stream=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy fetch failed: {e}")

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Upstream returned an error")

    from fastapi.responses import StreamingResponse

    content_type = r.headers.get("Content-Type", "video/mp4")
    return StreamingResponse(r.iter_content(chunk_size=8192), media_type=content_type)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
