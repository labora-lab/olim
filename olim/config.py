from environs import env

env.read_env()

DATABASE_URL: str = env("DATABASE_URL")
