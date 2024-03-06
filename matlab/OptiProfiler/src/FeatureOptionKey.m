classdef FeatureOptionKey
%FEATUREOPTIONKEY enumerates options for defining features.
    
    enumeration
        DISTRIBUTION ('distribution')
        MODIFIER ('modifier')
        N_RUNS ('n_runs')
        ORDER ('order')
        PARAMETER ('parameter')
        RATE_NAN ('rate_nan')
        SIGNIFICANT_DIGITS ('significant_digits')
        TYPE ('type')
    end
    properties
        value
    end
    methods
        function obj = FeatureOptionKey(inputValue)
            obj.value = inputValue;
        end
    end
end