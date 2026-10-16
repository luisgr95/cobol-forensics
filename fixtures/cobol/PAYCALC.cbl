      *----------------------------------------------------------------*
      * PAYCALC  INTEREST ON AN OVERDUE BALANCE                        *
      * SYNTHETIC SAMPLE. Not derived from any real system.            *
      *                                                                *
      * The rounding here is the kind of rule that only exists in the
      * code: COMPUTE without ROUNDED truncates toward zero, so a
      * faithful rewrite must truncate too.                            *
      *----------------------------------------------------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYCALC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE-TABLE.
           05  WS-RATE                     PIC S9V9(4) COMP-3
                                           OCCURS 4 TIMES.
       01  WS-TIER                         PIC 9 COMP.
       LINKAGE SECTION.
       01  LK-BALANCE                      PIC S9(9)V99 COMP-3.
       01  LK-CREDIT-LIMIT                 PIC S9(7)V99 COMP-3.
       01  LK-INTEREST                     PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION USING LK-BALANCE
                                LK-CREDIT-LIMIT
                                LK-INTEREST.
       MAIN-LOGIC.
           PERFORM LOAD-RATES
           PERFORM SELECT-TIER
           PERFORM COMPUTE-INTEREST
           GOBACK.
       LOAD-RATES.
           MOVE 0.0150 TO WS-RATE (1)
           MOVE 0.0225 TO WS-RATE (2)
           MOVE 0.0310 TO WS-RATE (3)
           MOVE 0.0475 TO WS-RATE (4).
       SELECT-TIER.
           EVALUATE TRUE
               WHEN LK-BALANCE <= 0
                   MOVE 1 TO WS-TIER
               WHEN LK-BALANCE <= LK-CREDIT-LIMIT
                   MOVE 2 TO WS-TIER
               WHEN LK-BALANCE <= 100000
                   MOVE 3 TO WS-TIER
               WHEN OTHER
                   MOVE 4 TO WS-TIER
           END-EVALUATE.
       COMPUTE-INTEREST.
           IF LK-BALANCE <= 0
               MOVE ZERO TO LK-INTEREST
           ELSE
               COMPUTE LK-INTEREST =
                   LK-BALANCE * WS-RATE (WS-TIER)
           END-IF.
