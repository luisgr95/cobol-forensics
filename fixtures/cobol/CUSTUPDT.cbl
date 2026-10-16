      *----------------------------------------------------------------*
      * CUSTUPDT  NIGHTLY CUSTOMER BALANCE UPDATE                      *
      * SYNTHETIC SAMPLE. Not derived from any real system.            *
      *----------------------------------------------------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTUPDT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO CUSTIN
               ORGANIZATION IS SEQUENTIAL.
           SELECT REPORT-FILE   ASSIGN TO RPTOUT
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUSTOMER-FILE
           RECORDING MODE IS F.
           COPY CUSTREC.
       FD  REPORT-FILE
           RECORDING MODE IS F.
       01  REPORT-LINE                     PIC X(133).
       WORKING-STORAGE SECTION.
       01  WS-COUNTERS.
           05  WS-READ-COUNT               PIC S9(9) COMP-3 VALUE ZERO.
           05  WS-UPDATE-COUNT             PIC S9(9) COMP-3 VALUE ZERO.
           05  WS-REJECT-COUNT             PIC S9(9) COMP-3 VALUE ZERO.
       01  WS-FLAGS.
           05  WS-EOF-FLAG                 PIC X VALUE 'N'.
               88  WS-END-OF-FILE          VALUE 'Y'.
       01  WS-NEXT-PGM                     PIC X(8) VALUE SPACES.
       01  WS-INTEREST                     PIC S9(7)V99 COMP-3.
       01  WS-SQLCODE-DISP                 PIC -9(9).
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN-CONTROL.
           PERFORM INITIALIZE-RUN
           PERFORM PROCESS-CUSTOMERS UNTIL WS-END-OF-FILE
           PERFORM FINALIZE-RUN
           GOBACK.
       INITIALIZE-RUN.
           OPEN INPUT CUSTOMER-FILE
           OPEN OUTPUT REPORT-FILE
           DISPLAY 'CUSTUPDT STARTING - CALL THE OPERATOR IF IT ABENDS'.
       PROCESS-CUSTOMERS.
           READ CUSTOMER-FILE
               AT END SET WS-END-OF-FILE TO TRUE
           END-READ
           IF NOT WS-END-OF-FILE
               ADD 1 TO WS-READ-COUNT
               PERFORM VALIDATE-CUSTOMER
               PERFORM APPLY-INTEREST
           END-IF.
       VALIDATE-CUSTOMER.
           CALL 'VALIDATE' USING CUSTOMER-RECORD
                                 WS-REJECT-COUNT.
       APPLY-INTEREST.
           IF CUST-BILLABLE
               CALL 'PAYCALC' USING CUST-BALANCE
                                    CUST-CREDIT-LIMIT
                                    WS-INTEREST
               EXEC SQL
                   UPDATE CUSTOMER_ACCT
                      SET ACCT_BALANCE = :CUST-BALANCE
                    WHERE CUST_ID = :CUST-ID
               END-EXEC
               IF SQLCODE NOT = 0
                   MOVE SQLCODE TO WS-SQLCODE-DISP
                   DISPLAY 'DB2 UPDATE FAILED ' WS-SQLCODE-DISP
                   ADD 1 TO WS-REJECT-COUNT
               ELSE
                   ADD 1 TO WS-UPDATE-COUNT
               END-IF
           END-IF.
       FINALIZE-RUN.
           EXEC SQL
               SELECT COUNT(*) INTO :WS-READ-COUNT
                 FROM CUSTOMER_ACCT
                WHERE ACCT_STATUS = 'A'
           END-EXEC
           PERFORM WRITE-TOTALS
           CLOSE CUSTOMER-FILE
           CLOSE REPORT-FILE
           MOVE 'CUSTRPT' TO WS-NEXT-PGM
           CALL WS-NEXT-PGM.
       WRITE-TOTALS.
           MOVE SPACES TO REPORT-LINE
           WRITE REPORT-LINE.
       UNUSED-DIAGNOSTIC.
           DISPLAY 'NEVER PERFORMED BY ANYTHING'.
