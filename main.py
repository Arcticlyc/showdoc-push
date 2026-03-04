from src.showdoc_push import ShowDocPush


def main():
    showdoc_push = ShowDocPush()

    qrcode_url = showdoc_push.start_qrcode_login(poll_timeout=10)
    print(f"请扫码登录，二维码 URL: {qrcode_url}")

    showdoc_push.wait_for_login()
    print(showdoc_push.token)


if __name__ == "__main__":
    main()
