# A bearer-token verifier. The account is a CLAIM, not a row scope.
REQUIRED_CLAIMS = ("account_id",)

def principal(claims):
    """The account this token acts for, read off the verified token."""
    return claims.get("account_id")
