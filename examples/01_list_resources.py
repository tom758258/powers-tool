from powers_tool_core.connection import list_resources


def main() -> None:
    resources = list_resources()
    if not resources:
        print("No VISA resources found.")
        return

    for resource in resources:
        print(resource)


if __name__ == "__main__":
    main()
