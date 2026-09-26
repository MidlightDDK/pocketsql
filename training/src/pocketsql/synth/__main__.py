from pocketsql._stub import stub

main = stub(
    "pocketsql.synth",
    "M3",
    lambda p: p.add_argument("--n", type=int, default=200, help="pairs per schema"),
)

if __name__ == "__main__":
    main()
