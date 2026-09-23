"""`python -m receiver` 의 입구. 본체는 `receiver/cli.py` 다 — 여기는 부르기만 한다.

가져오기만으로 돌지 않는다 — 문서 도구나 패키지 훑기가 이 모듈을 가져오면 인자를 읽고 끝나 버린다.
"""

from receiver.cli import main

if __name__ == "__main__":
    main()
