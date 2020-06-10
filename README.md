# ipop-test
Development of tests for ipop-project

# Run the tests with : 
```
python -m unittest D:/UF/OPS/Work/code/Controllers/controller/test/SignalTest.py
```

# Known problems

The terminal freezes and does not come back to the prompt after the tests have been run. - Have to fix

# Running the coverage tool
1) Install the coverage tool 
```
python -m pip install coverage
```
2) Run the coverage tool 
```
python -m coverage run -m unittest D:/UF/OPS/Work/code/Controllers/controller/test/SignalTest.py
```
3) View the report in HTML.
```
pyton -m coverage html
```
4) The html folder is created in the same folder as your project. Open *index.html* to view the coverage. You can click on each file to view the line by line coverage.

For more details on coverage refer to [Coverage.py](https://coverage.readthedocs.io/en/coverage-5.1/#:~:text=Coverage.py,gauge%20the%20effectiveness%20of%20tests).
