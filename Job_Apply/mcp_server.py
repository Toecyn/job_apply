"""
Job Intelligence MCP Server
Exposes job pipeline capabilities as MCP tools callable by any AI agent.

Run: python3 mcp_server.py
Connect via Claude Desktop or any MCP-compatible client.
"""
import sqlite3
import json
import asyncio
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

DB_PATH = "tracker.db"
app = Server("job-intelligence")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="search_jobs",
            description="Search for strong job matches in the pipeline. Returns jobs filtered by score, market, and freshness.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_score": {
                        "type": "integer",
                        "description": "Minimum match score 0-100. Use 80 for strong matches, 70 for good matches.",
                        "default": 75
                    },
                    "market": {
                        "type": "string",
                        "enum": ["all", "canada", "ottawa", "us_remote"],
                        "description": "Market to search in.",
                        "default": "all"
                    },
                    "fresh_hours": {
                        "type": "integer",
                        "description": "Only return jobs posted within this many hours. Use 24, 48, or 72.",
                        "default": 72
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 10
                    }
                }
            }
        ),
        types.Tool(
            name="get_job",
            description="Get full details for a specific job including the complete job description.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job ID from search_jobs results."
                    }
                },
                "required": ["job_id"]
            }
        ),
        types.Tool(
            name="get_pipeline_stats",
            description="Get operational statistics for the job intelligence pipeline — total jobs, score distribution, AI call costs, application pipeline status.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_skills",
            description="Get the interview preparation skills bank — enterprise AI concepts demonstrated through real system work, with interview questions and STAR answers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "Filter by enterprise concept keyword. Leave empty for all skills."
                    }
                }
            }
        ),
        types.Tool(
            name="get_applications",
            description="Get the current application pipeline — jobs marked as applied, reviewing, or interviewing.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):

    if name == "search_jobs":
        min_score = arguments.get("min_score", 75)
        market = arguments.get("market", "all")
        fresh_hours = arguments.get("fresh_hours", 72)
        limit = arguments.get("limit", 10)

        conn = get_db()
        query = """
            SELECT id, title, company, location, score,
                   search_pass, is_remote, date_found, job_url,
                   score_reasons, score_gaps
            FROM jobs
            WHERE is_stale = 0
            AND score >= ?
            AND length(description) >= 200
        """
        params = [min_score]

        if market != "all":
            query += " AND search_pass = ?"
            params.append(market)

        if fresh_hours > 0:
            query += f" AND date_found >= datetime('now', '-{fresh_hours} hours')"

        query += " ORDER BY score DESC LIMIT ?"
        params.append(limit)

        jobs = conn.execute(query, params).fetchall()
        conn.close()

        results = []
        for job in jobs:
            j = dict(job)
            try:
                j["score_reasons"] = json.loads(j["score_reasons"] or "[]")
                j["score_gaps"] = json.loads(j["score_gaps"] or "[]")
            except Exception:
                pass
            results.append(j)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "count": len(results),
                "jobs": results
            }, indent=2)
        )]

    elif name == "get_job":
        job_id = arguments.get("job_id")
        conn = get_db()
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()

        if not job:
            return [types.TextContent(type="text", text=json.dumps({"error": "Job not found"}))]

        j = dict(job)
        try:
            j["score_reasons"] = json.loads(j["score_reasons"] or "[]")
            j["score_gaps"] = json.loads(j["score_gaps"] or "[]")
        except Exception:
            pass

        return [types.TextContent(type="text", text=json.dumps(j, indent=2))]

    elif name == "get_pipeline_stats":
        conn = get_db()

        stats = {
            "database": {
                "total_jobs": conn.execute("SELECT COUNT(*) FROM jobs WHERE is_stale = 0").fetchone()[0],
                "scored": conn.execute("SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL AND is_stale = 0").fetchone()[0],
                "strong_matches_70": conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 70 AND is_stale = 0").fetchone()[0],
                "strong_matches_85": conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 85 AND is_stale = 0").fetchone()[0],
                "fresh_24hrs": conn.execute("SELECT COUNT(*) FROM jobs WHERE date_found >= datetime('now', '-24 hours') AND is_stale = 0").fetchone()[0],
                "fresh_72hrs": conn.execute("SELECT COUNT(*) FROM jobs WHERE date_found >= datetime('now', '-72 hours') AND is_stale = 0").fetchone()[0],
            },
            "markets": {
                "canada": conn.execute("SELECT COUNT(*) FROM jobs WHERE search_pass = 'canada' AND is_stale = 0").fetchone()[0],
                "ottawa": conn.execute("SELECT COUNT(*) FROM jobs WHERE search_pass = 'ottawa' AND is_stale = 0").fetchone()[0],
                "us_remote": conn.execute("SELECT COUNT(*) FROM jobs WHERE search_pass = 'us_remote' AND is_stale = 0").fetchone()[0],
            },
            "applications": {
                "applied": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0],
                "reviewing": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'reviewing'").fetchone()[0],
                "interviewing": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'interviewing'").fetchone()[0],
                "offer": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'offer'").fetchone()[0],
            },
            "ai_calls": {
                "total_calls": conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0],
                "total_cost_usd": round(conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_calls").fetchone()[0], 4),
                "today_calls": conn.execute("SELECT COUNT(*) FROM ai_calls WHERE timestamp >= date('now')").fetchone()[0],
                "today_cost_usd": round(conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_calls WHERE timestamp >= date('now')").fetchone()[0], 4),
                "success_rate_pct": round(conn.execute("SELECT COALESCE(AVG(success),0)*100 FROM ai_calls").fetchone()[0], 1),
            },
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        conn.close()
        return [types.TextContent(type="text", text=json.dumps(stats, indent=2))]

    elif name == "get_skills":
        concept_filter = arguments.get("concept", "").lower()
        try:
            with open("data/skills.json") as f:
                data = json.load(f)
            skills = data.get("skills", [])
            if concept_filter:
                skills = [
                    s for s in skills
                    if concept_filter in s["enterprise_concept"].lower()
                    or any(concept_filter in t for t in s["tags"])
                ]
            return [types.TextContent(type="text", text=json.dumps({
                "count": len(skills),
                "skills": skills
            }, indent=2))]
        except Exception as e:
            return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

    elif name == "get_applications":
        conn = get_db()
        apps = conn.execute("""
            SELECT id, title, company, location, score,
                   status, resume_path, date_found
            FROM jobs
            WHERE status IN ('applied', 'reviewing', 'interviewing', 'offer')
            ORDER BY date_found DESC
        """).fetchall()
        conn.close()

        return [types.TextContent(type="text", text=json.dumps({
            "count": len(apps),
            "applications": [dict(a) for a in apps]
        }, indent=2))]

    else:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"})
        )]


async def main():
    print("Job Intelligence MCP Server starting...")
    print("Tools available:")
    print("  search_jobs       — find strong matches")
    print("  get_job           — full job details")
    print("  get_pipeline_stats — governance metrics")
    print("  get_skills        — interview prep data")
    print("  get_applications  — application pipeline")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
