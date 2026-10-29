REQUIRED_CLAIMS = ("account_id",)

def principal(claims):
    return claims.get("account_id")
