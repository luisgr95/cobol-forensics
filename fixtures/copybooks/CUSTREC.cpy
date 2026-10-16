      *----------------------------------------------------------------
      * CUSTREC  CUSTOMER MASTER RECORD
      *
      * SYNTHETIC SAMPLE. Written for this repository to exercise the
      * parser. Not derived from any real system.
      *
      * Deliberately includes the cases that break naive parsers:
      *   - REDEFINES over a group item
      *   - COMP-3 with an odd and an even digit count
      *   - COMP sized from its digit count, not its value range
      *   - OCCURS DEPENDING ON, making the record variable length
      *   - condition names nested under a subordinate field
      *
      * Total length: 172 bytes with CUST-PHONE-COUNT at its maximum.
      *----------------------------------------------------------------
       01  CUSTOMER-RECORD.
           05  CUST-ID                     PIC 9(8).
           05  CUST-STATUS                 PIC X.
               88  CUST-ACTIVE             VALUE 'A'.
               88  CUST-CLOSED             VALUE 'C'.
               88  CUST-SUSPENDED          VALUE 'S'.
               88  CUST-BILLABLE           VALUE 'A' 'S'.
           05  CUST-NAME.
               10  CUST-FIRST              PIC X(20).
               10  CUST-LAST               PIC X(30).
           05  CUST-NAME-FLAT REDEFINES CUST-NAME
                                           PIC X(50).
           05  CUST-BALANCE                PIC S9(9)V99 COMP-3.
           05  CUST-CREDIT-LIMIT           PIC S9(7)V99 COMP-3.
           05  CUST-OPEN-DATE              PIC 9(8).
           05  CUST-REGION-CODE            PIC 9(4) COMP.
           05  CUST-PHONE-COUNT            PIC 9(2).
           05  CUST-PHONES                 OCCURS 1 TO 5 TIMES
                                 DEPENDING ON CUST-PHONE-COUNT.
               10  CUST-PHONE-TYPE         PIC X.
                   88  PHONE-IS-MOBILE     VALUE 'M'.
                   88  PHONE-IS-LANDLINE   VALUE 'L'.
               10  CUST-PHONE-NUMBER       PIC X(15).
           05  FILLER                      PIC X(10).
