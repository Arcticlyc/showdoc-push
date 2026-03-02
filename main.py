from src.showdoc_push import ShowDocPush


def main():
    showdoc_push = ShowDocPush()

    qrcode_url = showdoc_push.qrcode_login()
    print(qrcode_url)

    print(showdoc_push.qrcode_login())

    print(showdoc_push.token)


if __name__ == "__main__":
    main()
