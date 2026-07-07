import asyncio
import asyncpg
from settings import settings

async def main():
    db_url = settings.database_url
    try:
        import socket
        host = db_url.split("@")[1].split(":")[0]
        socket.gethostbyname(host)
    except (socket.gaierror, IndexError):
        db_url = db_url.replace("@db:", "@localhost:")

    print("Connecting to database...")
    conn = await asyncpg.connect(dsn=db_url)
    try:
        print("Resetting chat conversations, leads, security events, and token metrics...")
        await conn.execute("""
            TRUNCATE TABLE 
                sessions, 
                leads, 
                unanswered_questions, 
                security_events 
            CASCADE;
        """)
        print("Database chat and token tables reset successfully!")
    except Exception as e:
        print(f"Error resetting database: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
