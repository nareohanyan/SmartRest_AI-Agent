import pymysql

conn = pymysql.connect(
    host="172.21.0.5",
    port=3306,
    user="root",
    password="pass",
    database="gastro_plazabackup",
    charset="utf8mb4"
)

try:
    with conn.cursor() as cur:
        cur.execute("SELECT * from profiles_users")
        print("Connected. Server version:", cur.fetchall())
finally:
    conn.close()