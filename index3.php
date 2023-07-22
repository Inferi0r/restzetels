<!DOCTYPE html>
<html>
<head>
    <title>Website Table Example</title>
</head>
<body>
    <table border="1">
        <tr>
            <th>Data</th>
            <th>Column 1</th>
            <th>Column 2</th>
            <th>Column 3</th>
            <th>Column 4</th>
            <th>Column 5</th>
            <th>Column 6</th>
            <th>Column 7</th>
            <th>Column 8</th>
            <th>Column 9</th>
            <th>Column 10</th>
        </tr>
        <?php
        // Data array for the table rows
        $data = array(
            array("Allego 300kWh DC G0015015-1<br>De Holle Bilt 1 - CPO: 94ct", "1 kWh", "start", "50kWh  / 1x", "Rate", "DC Operators NL", "Prijsinfo", "Note", "Column 8", "Column 9", "Column 10"),
            array("BMW/ MINI Charging (Ionity Plus)", "€ 0,2200", "€ 0,0000", "€ 11,00", "flat", "Ionity", '<a href="https://bmw-public-charging.com" target="_blank">bmw-public-charging.com</a><br><a href="https://mini-charging.com" target="_blank">mini-charging.com</a>', "€13,00 p/m (12mnd). BMW of MINI VIN vereist", "Column 8", "Column 9", "Column 10"),
            array("Freshmile", "€ 0,2520", "€ 0,0000", "€ 12,60", "flat+tijd", "Shell: 1x 300kW, 52x 175kW, 3x 150kW", '<a href="https://freshmile.com" target="_blank">freshmile.com</a>', "21ct/kWh + 7ct/pm Prijs bij ±100kWh/u laden", "Column 8", "Column 9", "Column 10"),
            array("Freshmile", "€ 0,2680", "€ 0,0000", "€ 13,40", "flat+tijd", "LMS: 15x 120kW", '<a href="https://freshmile.com" target="_blank">freshmile.com</a>', "25ct/kWh + 3ct/pm Prijs bij ±100kWh/u laden", "Column 8", "Column 9", "Column 10")
        );

        // Loop through the data and generate table rows
        foreach ($data as $row) {
            echo "<tr>";
            foreach ($row as $cell) {
                echo "<td>$cell</td>";
            }
            echo "</tr>";
        }
        ?>
    </table>
</body>
</html>
