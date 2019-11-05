'''
Created on Apr 25, 2019

@author: Javier Arroyo

This module contains the Data_Manager class with methods to add and  
access test case data within the resources folder of the
test case FMU.

'''

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import zipfile
from scipy import interpolate
import warnings
import os
import json

class Data_Manager(object):
    ''' This class has the functionality to store and retrieve the data 
    into and from the resources folder of the test case FMU. 
    
    To store the data, it assumes csv files are within a Resources directory 
    located in the same directory as the FMU.  All csv files are searched for 
    columns with keys following the BOPTEST data convention specified in the 
    categories.json file.
    
    To retrieve the data, it loads timeseries data and kpis.json into the 
    TestCase object managing the FMU upon deployment and provides methods
    to retrieve it as needed for forecasting purposes or for KPI calculations.
    
    '''

    def __init__(self, testcase=None):
        '''Initialize the Data_Manager class.
        
        Parameters
        ----------
        testcase: BOPTEST TestCase object, default is None
            Used if loading or retrieving data from a test case FMU.
            Not used if compiling test case data into an FMU.
            Default is None.
        
        '''
        
        # Point to the test case object
        self.case = testcase
        
        # Find path to data directory
        data_dir = os.path.join(\
            os.path.split(os.path.split(os.path.abspath(__file__))[0])[0],
            'data')
        
        # Load possible data keys
        with open(os.path.join(data_dir,'categories.json'),'r') as f:
            self.categories = json.loads(f.read()) 
        
    def _append_csv_data(self):
        '''Append data from any .csv file within the Resources folder
        of the testcase. The .csv file must contain a 'time' column 
        in seconds from the beginning of the year and one of the 
        keys defined within categories.kpis. Other data without these
        keys will be neglected.
        
        '''
        
        # Find all data keys
        all_keys = []
        for category in self.categories:
            all_keys.extend(self.categories[category])
        
        # Keep track of the data already appended to avoid duplication
        appended = {key: None for key in all_keys}
        
        # Search for .csv files in the resources folder
        for f in self.files:
            if f.endswith('.csv'):
                df = pd.read_csv(f)
                cols = df.keys()
                if 'time' in cols:
                    for col in cols.drop('time'):
                        # Raise error if col already appended
                        if appended[col] is not None:
                            raise ReferenceError('{0} in multiple files within the Resources folder. These are: {1}, and {2}'.format(col, appended[col], f))
                        # Trim df from cols that are not in categories
                        elif not any(col.startswith(key) for key in all_keys):
                            df.drop(col, inplace=True)
                        else:
                            appended[col] = f
                    # Copy the trimmed df if any col found in categories
                    if len(df.keys())>0:
                        df.to_csv(f+'_trimmed', index=False)
                        file_name = os.path.split(f)[1]
                        self.z_fmu.write(f+'_trimmed', os.path.join('resources',
                                         file_name))
                        os.remove(f+'_trimmed')
                else:
                    warnings.warn('The following file does not have '\
                    'time column and therefore no data is going to '\
                    'be used from this file as test case data.', Warning) 
                    print(f)
                    
    def save_data_and_kpisjson(self, fmu_path):
        '''Store all of the .csv and kpis.json test case data within the 
        resources folder of the fmu.
        
        Parameters
        ----------       
        fmu_path : string
            Path to the fmu where the data is to be saved. The reason
            to not get this path from the tescase config file is 
            that this method is called by the parser before the test 
            case is created. 
        
        '''
        
        # Open the fmu zip file in append mode
        self.z_fmu = zipfile.ZipFile(fmu_path,'a')
        
        # Find the models directory
        models_dir = os.path.split(os.path.abspath(fmu_path))[0]
        
        # Find the Resources folder
        resources_dir = os.path.join(models_dir, 'Resources')
        
        if os.path.exists(resources_dir):
            # Find all files within Resources folder
            self.files = []
            for root, _, files in os.walk(resources_dir):
                for f in files:
                    self.files.append(os.path.join(root,f))   
            
            # Write a copy all .csv files within the fmu resources folder
            self._append_csv_data() 
        else:
            warnings.warn('No Resources folder found for this FMU, ' \
                          'No additional data will be stored within the FMU.')
        
        # Find the kpis.json path
        kpi_path = os.path.join(models_dir, 'kpis.json')
        
        # Write a copy of the kpis.json within the fmu resources folder
        if os.path.exists(kpi_path):
            self.z_fmu.write(kpi_path, 
                             os.path.join('resources', 'kpis.json'))
        else:
            warnings.warn('No kpis.json found for this test case, ' \
                          'use the parser to get this file or otherwise create it.')
                
        # Close the fmu
        self.z_fmu.close()
        
    def get_data(self, horizon=24*3600, interval=None, index=None, 
                 category=None, plot=False):
        '''Retrieve test case data from the fmu. The data
        is stored within the csv files that are 
        located in the resources folder of the test case fmu.
        
        Parameters
        ----------
        horizon : int, default is 24*3600
            Length of the requested forecast in seconds. By default one
            day will be used. 
        interval : int, default is None
            resampling time interval in seconds. If None,
            the test case step will be used instead.
        index : numpy array, default is None
            time vector for which the data points are requested.
            The interpolation is linear for the weather data
            and forward fill for the other data categories. If 
            index is None, the default case step is used as default. 
        category : string, default is None
            Type of data to retrieve from the test case.
            If None it will return all available test case
            data without filtering it by any category. 
            The possible options are specified at categories.json.
        plot : Boolean, default is False
            True if desired to plot the retrieved data
            
        Returns
        -------
        data: dict 
            Dictionary with the requested forecast data
            {<variable_name>:<variable_forecast_trajectory>}
            where <variable_name> is a string with the variable
            key and <variable_forecast_trajectory> is a list with
            the data values. 'time' is included as a variable
        
        Notes
        -----
        The loading and pre-processing of the data happens only 
        once (at load_data_and_kpisjson) to reduce the computational 
        load during the co-simulation
        
        '''
        
        # Filter the requested data columns
        if category is not None:
            cols = [col for col in self.case.data if \
                    any(col.startswith(key) for key in self.categories[category])]
            data_slice = self.case.data.loc[:,cols]
        else:
            data_slice = self.case.data
            
        # If no index use horizon and interval 
        if index is None:
            # Use the test case start time 
            start = self.case.start_time
            stop  = start + horizon
            # Use step if None interval provided
            if interval is None:
                interval=self.case.step
            # Define the index. Make sure last point is included if 
            # possible. If interval is not an exact divisor of stop,
            # the closest possible point under stop will be the end 
            # point in order to keep interval unchanged among index. 
            index = np.arange(start,stop+0.1,interval).astype(int)

        # Reindex to the desired index
        data_slice_reindexed = data_slice.reindex(index)
        
        for key in data_slice_reindexed.keys():
            # Use linear interpolation for continuous variables
            if key in self.categories['weather']:
                f = interpolate.interp1d(self.case.data.index,
                    self.case.data[key], kind='linear')
            # Use forward fill for discrete variables
            else:
                f = interpolate.interp1d(self.case.data.index,
                    self.case.data[key], kind='zero')
            data_slice_reindexed.loc[:,key] = f(index)
        
        if plot:
            if category is None:
                to_plot = data_slice_reindexed.keys()
            else: 
                to_plot = self.categories[category]
            for var in to_plot:
                data_slice_reindexed[var].plot()
                plt.legend()
                plt.show()
        
        # Reset the index to keep the 'time' column in the data
        # Transform data frame to dictionary
        return data_slice_reindexed.reset_index().to_dict('list')
    
    def load_data_and_kpisjson(self):
        '''Load the data and kpis.json from the resources folder of the fmu 
        into the test case object.  The data is resampled according to the 
        minimum sampling rate, where weather is linearly interpolated and 
        schedules use a forward-fill.
        
        '''
        
        # Point to the fmu zip file
        z_fmu = zipfile.ZipFile(self.case.fmupath, 'r')
        # The following will work in any OS because the zip format 
        # specifies a forward slash.
        
        # Load kpi json
        json_str = z_fmu.open('resources/kpis.json').read()
        self.case.kpi_json = json.loads(json_str)
        
        # Find the test case data files
        files = []
        for f in z_fmu.namelist():
            if f.startswith('resources/') and f.endswith('.csv'):
                files.append(f)
        
        # Find the minimum sampling resolution
        sampling = 3600. 
        for f in files:
            df = pd.read_csv(z_fmu.open(f))
            if 'time' in df.keys():
                new_sampling = df.iloc[1]['time']-df.iloc[0]['time']
                if new_sampling<sampling:
                    sampling=new_sampling
                    
        # Define the index for one year with the minimum sampling found
        index = np.arange(0.,3.1536e+7,sampling,dtype='int')
        
        # Find all data keys
        all_keys = []
        for category in self.categories:
            all_keys.extend(self.categories[category])
        
        # Initialize test case data frame
        self.case.data = \
            pd.DataFrame(index=index, columns=all_keys).rename_axis('time')
        
        # Load the test case data
        for f in files:
            df = pd.read_csv(z_fmu.open(f))
            cols = df.keys()
            if 'time' in cols:
                for col in cols.drop('time'):
                    for category in self.categories:
                        # Use linear interpolation for continuous variables
                        if any(col.startswith(key) for key in self.categories['weather']):
                            g = interpolate.interp1d(df['time'],df[col], 
                                kind='linear')
                            self.case.data.loc[:,col] = \
                                g(self.case.data.index)
                        # Use forward fill for discrete variables
                        elif any(col.startswith(key) for key in self.categories[category]):
                            g = interpolate.interp1d(df['time'],df[col], 
                                kind='zero')
                            self.case.data.loc[:,col] = \
                                g(self.case.data.index)
            else:
                warnings.warn('The following file does not have '\
                'time column and therefore no data is going to '\
                'be used from this file as test case data.', Warning) 
                print(f)
        
        # Close the fmu
        z_fmu.close()        
        
        # Convert any string formatted numbers to floats.
        self.case.data = self.case.data.applymap(float)

        
if __name__ == "__main__":
    import sys
    case_dir = os.path.join(\
        os.path.split(os.path.split(os.path.abspath(__file__))[0])[0], 
        'testcase2')
    # Append the case directory to see the config file
    sys.path.append(case_dir)
    
    from testcase import TestCase
    case=TestCase()
    man = Data_Manager(case)
    data=man.get_data()
        