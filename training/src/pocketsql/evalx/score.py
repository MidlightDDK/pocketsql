from pocketsql._stub import stub

main = stub(
    "pocketsql.evalx.score",
    "M2",
    lambda p: p.add_argument("predictions", nargs="?", help="predictions .jsonl"),
)

if __name__ == "__main__":
    main()
