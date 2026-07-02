import os
import re

from .persistence import MySQLExperimentStore


def validate_database_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("KG_MYSQL_DATABASE 只能包含字母、数字和下划线")
    return name


def initialize_mysql():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("请先安装 pymysql") from exc

    database = validate_database_name(
        os.getenv("KG_MYSQL_DATABASE", "kg_experiments")
    )
    connection = pymysql.connect(
        host=os.getenv("KG_MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("KG_MYSQL_PORT", "3306")),
        user=os.getenv("KG_MYSQL_USER", "root"),
        password=os.getenv("KG_MYSQL_PASSWORD", ""),
        charset=os.getenv("KG_MYSQL_CHARSET", "utf8mb4"),
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()

    store = MySQLExperimentStore.from_env()
    store.initialize_schema()
    store.close()
    print(f"MySQL 实验库初始化完成：{database}")


if __name__ == "__main__":
    initialize_mysql()
